"""Transactional CSV ingestion for SalesPulse.

Design rules:
* Static validation runs before the write transaction.
* Cross-table validation and writes happen in one database transaction.
* Expected row-level problems become rejection records, not exceptions.
* Unexpected failures roll the whole import back and a failed batch is logged.
* Re-importing identical rows yields "unchanged", never duplicate business data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from salespulse.database import require_initialized
from salespulse.exceptions import (
    ImportExecutionError,
    InputFileError,
    SalesPulseError,
    SchemaError,
)
from salespulse.schema import DATASET_KEY, EXPECTED_COLUMNS, INGESTION_ORDER
from salespulse.transformations import round_money
from salespulse.validation import (
    RowRejection,
    ValidationOutcome,
    read_source_csv,
    validate_dataset,
)


@dataclass(slots=True)
class ImportSummary:
    import_id: str
    dataset: str
    source_file: str
    file_sha256: str
    status: str
    started_at: str
    completed_at: str | None = None
    total_rows: int = 0
    inserted_rows: int = 0
    updated_rows: int = 0
    unchanged_rows: int = 0
    rejected_rows: int = 0
    error_message: str | None = None
    dry_run: bool = False
    rejections: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid_rows(self) -> int:
        return self.inserted_rows + self.updated_rows + self.unchanged_rows

    def to_dict(self, *, include_rejections: bool = True) -> dict[str, Any]:
        data = {
            "import_id": self.import_id,
            "dataset": self.dataset,
            "source_file": self.source_file,
            "file_sha256": self.file_sha256,
            "status": self.status,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_rows": self.total_rows,
            "inserted_rows": self.inserted_rows,
            "updated_rows": self.updated_rows,
            "unchanged_rows": self.unchanged_rows,
            "valid_rows": self.valid_rows,
            "rejected_rows": self.rejected_rows,
            "error_message": self.error_message,
        }
        if include_rejections:
            data["rejections"] = self.rejections
        return data


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_import_id() -> str:
    return f"IMP-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"


def detect_dataset(path: str | Path) -> str:
    stem = Path(path).stem
    candidates = [name for name in INGESTION_ORDER if stem.lower() == name]
    if not candidates:
        raise SchemaError(
            f"Could not detect dataset from filename {Path(path).name!r}. "
            f"Supported names: {', '.join(name + '.csv' for name in INGESTION_ORDER)}"
        )
    return candidates[0]


def _hash_file(path: str | Path) -> str:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 2)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def _row_dict(row: pd.Series) -> dict[str, Any]:
    return {str(key): _python_scalar(value) for key, value in row.to_dict().items()}


def _fetch_mapping(conn: Connection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(text(sql), params).mappings().first()
    return None if row is None else dict(row)


def _record_failed_import(
    engine: Engine,
    *,
    dataset: str,
    source_file: str | Path,
    file_hash: str,
    error_message: str,
    total_rows: int = 0,
) -> None:
    """Best-effort audit of a failed import, outside the failed transaction."""
    if dataset not in INGESTION_ORDER:
        return
    now = _utc_now()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_batches (
                        import_id, dataset, source_file, file_sha256, started_at,
                        completed_at, status, total_rows, error_message
                    ) VALUES (
                        :import_id, :dataset, :source_file, :file_sha256, :started_at,
                        :completed_at, 'failed', :total_rows, :error_message
                    )
                    """
                ),
                {
                    "import_id": _new_import_id(),
                    "dataset": dataset,
                    "source_file": Path(source_file).name,
                    "file_sha256": file_hash,
                    "started_at": now,
                    "completed_at": now,
                    "total_rows": total_rows,
                    "error_message": error_message[:2000],
                },
            )
    except SQLAlchemyError:
        # Never hide the original import error because the audit write failed.
        pass


def ingest_file(
    engine: Engine,
    path: str | Path,
    dataset: str | None = None,
    *,
    normalize_labels: bool = True,
    as_of_date: date | None = None,
    dry_run: bool = False,
) -> ImportSummary:
    """Validate and ingest one CSV file.

    Args:
        engine: Initialized SQLAlchemy engine.
        path: CSV source path.
        dataset: One of the supported datasets; auto-detected from filename if omitted.
        normalize_labels: Map documented categorical aliases to canonical values.
        as_of_date: Date used for "not in the future" checks. Defaults to today.
        dry_run: Perform the full validation and DB writes, then roll back.
    """
    require_initialized(engine)
    dataset = dataset or detect_dataset(path)
    if dataset not in INGESTION_ORDER:
        raise SchemaError(f"Unsupported dataset {dataset!r}")
    file_path = Path(path)
    file_hash = _hash_file(file_path)
    full_frame: pd.DataFrame | None = None
    started_at = _utc_now()

    try:
        full_frame = read_source_csv(file_path)
        outcome = validate_dataset(
            full_frame,
            dataset,
            as_of_date=as_of_date,
            normalize_labels=normalize_labels,
        )
    except (InputFileError, SchemaError) as exc:
        if not dry_run:
            _record_failed_import(
                engine,
                dataset=dataset,
                source_file=file_path,
                file_hash=file_hash,
                error_message=str(exc),
                total_rows=0 if full_frame is None else len(full_frame),
            )
        raise

    if dry_run:
        try:
            with engine.connect() as conn:
                transaction = conn.begin()
                try:
                    summary = _ingest_in_transaction(
                        conn,
                        dataset=dataset,
                        file_path=file_path,
                        file_hash=file_hash,
                        full_frame=full_frame,
                        outcome=outcome,
                        started_at=started_at,
                    )
                finally:
                    transaction.rollback()
            summary.dry_run = True
            return summary
        except SalesPulseError:
            raise
        except Exception as exc:  # noqa: BLE001 - converted to a domain error
            raise ImportExecutionError(f"Validation dry run failed: {exc}") from exc

    try:
        with engine.begin() as conn:
            return _ingest_in_transaction(
                conn,
                dataset=dataset,
                file_path=file_path,
                file_hash=file_hash,
                full_frame=full_frame,
                outcome=outcome,
                started_at=started_at,
            )
    except SalesPulseError as exc:
        _record_failed_import(
            engine,
            dataset=dataset,
            source_file=file_path,
            file_hash=file_hash,
            error_message=str(exc),
            total_rows=len(full_frame),
        )
        raise
    except Exception as exc:  # noqa: BLE001 - transaction safety boundary
        _record_failed_import(
            engine,
            dataset=dataset,
            source_file=file_path,
            file_hash=file_hash,
            error_message=f"{type(exc).__name__}: {exc}",
            total_rows=len(full_frame),
        )
        raise ImportExecutionError(
            f"Import failed and was rolled back. No business rows were partially written. "
            f"Cause: {exc}"
        ) from exc


def _ingest_in_transaction(
    conn: Connection,
    *,
    dataset: str,
    file_path: Path,
    file_hash: str,
    full_frame: pd.DataFrame,
    outcome: ValidationOutcome,
    started_at: str,
) -> ImportSummary:
    import_id = _new_import_id()
    conn.execute(
        text(
            """
            INSERT INTO import_batches (
                import_id, dataset, source_file, file_sha256, started_at, status,
                total_rows
            ) VALUES (
                :import_id, :dataset, :source_file, :file_sha256, :started_at,
                'processing', :total_rows
            )
            """
        ),
        {
            "import_id": import_id,
            "dataset": dataset,
            "source_file": file_path.name,
            "file_sha256": file_hash,
            "started_at": started_at,
            "total_rows": len(full_frame),
        },
    )

    counters = {"inserted": 0, "updated": 0, "unchanged": 0}
    business_rejections: list[RowRejection] = []
    processor = {
        "customers": _process_customer,
        "products": _process_product,
        "orders": _process_order,
        "order_items": _process_order_item,
        "returns": _process_return,
        "payments": _process_payment,
    }[dataset]

    for position, (_, row) in enumerate(outcome.valid_rows.iterrows()):
        row_number = outcome.valid_row_numbers[position]
        normalized = _row_dict(row)
        errors, action = processor(conn, normalized)
        if errors:
            raw_index = row_number - 2
            raw = (
                _row_dict(full_frame.iloc[raw_index])
                if 0 <= raw_index < len(full_frame)
                else normalized
            )
            business_rejections.append(
                RowRejection(row_number=row_number, raw_data=raw, reasons=errors)
            )
        elif action:
            counters[action] += 1

    rejections = [*outcome.rejections, *business_rejections]
    rejections.sort(key=lambda item: item.row_number)
    if rejections:
        conn.execute(
            text(
                """
                INSERT INTO rejected_records (
                    import_id, dataset, row_number, raw_data, reasons
                ) VALUES (
                    :import_id, :dataset, :row_number, :raw_data, :reasons
                )
                """
            ),
            [rejection.as_record(dataset, import_id) for rejection in rejections],
        )

    completed_at = _utc_now()
    status = "partial" if rejections else "success"
    rejected_count = len(rejections)
    conn.execute(
        text(
            """
            UPDATE import_batches
            SET completed_at = :completed_at,
                status = :status,
                inserted_rows = :inserted_rows,
                updated_rows = :updated_rows,
                unchanged_rows = :unchanged_rows,
                rejected_rows = :rejected_rows
            WHERE import_id = :import_id
            """
        ),
        {
            "completed_at": completed_at,
            "status": status,
            "inserted_rows": counters["inserted"],
            "updated_rows": counters["updated"],
            "unchanged_rows": counters["unchanged"],
            "rejected_rows": rejected_count,
            "import_id": import_id,
        },
    )

    summary = ImportSummary(
        import_id=import_id,
        dataset=dataset,
        source_file=file_path.name,
        file_sha256=file_hash,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        total_rows=len(full_frame),
        inserted_rows=counters["inserted"],
        updated_rows=counters["updated"],
        unchanged_rows=counters["unchanged"],
        rejected_rows=rejected_count,
        rejections=[rejection.as_record(dataset, import_id) for rejection in rejections],
    )
    if summary.valid_rows + summary.rejected_rows != summary.total_rows:
        raise ImportExecutionError(
            "Internal accounting error: accepted plus rejected rows do not equal total rows"
        )
    return summary


# ---------------------------------------------------------------------------
# Per-dataset validation and upserts
# ---------------------------------------------------------------------------


def _diff(existing: dict[str, Any], values: dict[str, Any], fields: tuple[str, ...]) -> bool:
    for field_name in fields:
        old = _python_scalar(existing.get(field_name))
        new = _python_scalar(values.get(field_name))
        if isinstance(old, float) and isinstance(new, float):
            if round(old, 2) != round(new, 2):
                return True
        elif old != new:
            return True
    return False


def _process_customer(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    existing = _fetch_mapping(
        conn,
        "SELECT * FROM customers WHERE customer_id = :customer_id",
        {"customer_id": values["customer_id"]},
    )
    email_owner = _fetch_mapping(
        conn,
        "SELECT customer_id FROM customers WHERE email = :email AND customer_id <> :customer_id",
        {"email": values["email"], "customer_id": values["customer_id"]},
    )
    if email_owner:
        errors.append(
            f"email {values['email']!r} already belongs to customer {email_owner['customer_id']!r}"
        )
    if errors:
        return errors, None

    fields = ("first_name", "last_name", "email", "signup_date", "region", "country", "city")
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO customers (
                    customer_id, first_name, last_name, email, signup_date,
                    region, country, city
                ) VALUES (
                    :customer_id, :first_name, :last_name, :email, :signup_date,
                    :region, :country, :city
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE customers
                SET first_name = :first_name, last_name = :last_name, email = :email,
                    signup_date = :signup_date, region = :region, country = :country,
                    city = :city
                WHERE customer_id = :customer_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


def _process_product(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    existing = _fetch_mapping(
        conn,
        "SELECT * FROM products WHERE product_id = :product_id",
        {"product_id": values["product_id"]},
    )
    fields = (
        "product_name",
        "category",
        "unit_price",
        "unit_cost",
        "launch_date",
        "is_active",
    )
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO products (
                    product_id, product_name, category, unit_price, unit_cost,
                    launch_date, is_active
                ) VALUES (
                    :product_id, :product_name, :category, :unit_price, :unit_cost,
                    :launch_date, :is_active
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE products
                SET product_name = :product_name, category = :category,
                    unit_price = :unit_price, unit_cost = :unit_cost,
                    launch_date = :launch_date, is_active = :is_active
                WHERE product_id = :product_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


def _process_order(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    customer = _fetch_mapping(
        conn,
        "SELECT customer_id, signup_date FROM customers WHERE customer_id = :customer_id",
        {"customer_id": values["customer_id"]},
    )
    if customer is None:
        errors.append(f"unknown customer_id {values['customer_id']!r}")
    elif values["order_date"] < customer["signup_date"]:
        errors.append(
            f"order_date {values['order_date']} is before the customer's signup_date "
            f"{customer['signup_date']}"
        )
    existing = _fetch_mapping(
        conn,
        "SELECT * FROM orders WHERE order_id = :order_id",
        {"order_id": values["order_id"]},
    )
    if existing is not None:
        if existing["customer_id"] != values["customer_id"]:
            errors.append("customer_id is immutable for an existing order")
        if existing["order_date"] != values["order_date"]:
            errors.append("order_date is immutable for an existing order")
        old_status = str(existing["status"])
        new_status = str(values["status"])
        if old_status != new_status:
            allowed = old_status == "pending" and new_status in {"completed", "cancelled"}
            if not allowed:
                errors.append(
                    f"invalid status transition {old_status!r} -> {new_status!r}; "
                    "only pending orders may move to completed or cancelled"
                )
    if errors:
        return errors, None

    fields = ("status", "shipping_region", "shipping_country", "shipping_city")
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO orders (
                    order_id, customer_id, order_date, status, shipping_region,
                    shipping_country, shipping_city
                ) VALUES (
                    :order_id, :customer_id, :order_date, :status, :shipping_region,
                    :shipping_country, :shipping_city
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE orders
                SET status = :status, shipping_region = :shipping_region,
                    shipping_country = :shipping_country, shipping_city = :shipping_city
                WHERE order_id = :order_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


def _process_order_item(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    order = _fetch_mapping(
        conn,
        "SELECT order_id, status FROM orders WHERE order_id = :order_id",
        {"order_id": values["order_id"]},
    )
    product = _fetch_mapping(
        conn,
        "SELECT product_id FROM products WHERE product_id = :product_id",
        {"product_id": values["product_id"]},
    )
    if order is None:
        errors.append(f"unknown order_id {values['order_id']!r}")
    if product is None:
        errors.append(f"unknown product_id {values['product_id']!r}")
    existing = _fetch_mapping(
        conn,
        "SELECT * FROM order_items WHERE order_item_id = :order_item_id",
        {"order_item_id": values["order_item_id"]},
    )
    duplicate_pair = _fetch_mapping(
        conn,
        """
        SELECT order_item_id FROM order_items
        WHERE order_id = :order_id AND product_id = :product_id
          AND order_item_id <> :order_item_id
        """,
        {
            "order_id": values["order_id"],
            "product_id": values["product_id"],
            "order_item_id": values["order_item_id"],
        },
    )
    if duplicate_pair:
        errors.append(
            f"order {values['order_id']!r} already has product {values['product_id']!r} "
            f"on item {duplicate_pair['order_item_id']!r}"
        )
    if existing is not None:
        if existing["order_id"] != values["order_id"]:
            errors.append("order_id is immutable for an existing order item")
        if existing["product_id"] != values["product_id"]:
            errors.append("product_id is immutable for an existing order item")
        fields = ("quantity", "unit_price", "discount_rate")
        changing = _diff(existing, values, fields)
        if changing and order is not None and order["status"] != "pending":
            errors.append(
                "order items may only be changed while their order is pending; "
                f"this order is {order['status']}"
            )
    if errors:
        return errors, None

    fields = ("quantity", "unit_price", "discount_rate")
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO order_items (
                    order_item_id, order_id, product_id, quantity, unit_price,
                    discount_rate
                ) VALUES (
                    :order_item_id, :order_id, :product_id, :quantity, :unit_price,
                    :discount_rate
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE order_items
                SET quantity = :quantity, unit_price = :unit_price,
                    discount_rate = :discount_rate
                WHERE order_item_id = :order_item_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


def _process_return(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    item = _fetch_mapping(
        conn,
        """
        SELECT oi.order_item_id, oi.order_id, oi.quantity, oi.unit_price,
               oi.discount_rate, o.order_date, o.status AS order_status
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE oi.order_item_id = :order_item_id
        """,
        {"order_item_id": values["order_item_id"]},
    )
    if item is None:
        errors.append(f"unknown order_item_id {values['order_item_id']!r}")
    else:
        if item["order_status"] != "completed":
            errors.append(
                f"returns are only allowed for completed orders; order "
                f"{item['order_id']!r} is {item['order_status']}"
            )
        if values["return_date"] < item["order_date"]:
            errors.append(
                f"return_date {values['return_date']} is before order_date {item['order_date']}"
            )
        if values["status"] != "approved" and float(values["refund_amount"]) != 0.0:
            errors.append("refund_amount must be 0 unless return status is 'approved'")
        line_net = round_money(
            float(item["quantity"]) * float(item["unit_price"]) * (1 - float(item["discount_rate"]))
        )
        approved_cap = round_money(
            float(values["quantity"])
            * float(item["unit_price"])
            * (1 - float(item["discount_rate"]))
        )
        if values["status"] == "approved" and float(values["refund_amount"]) > approved_cap + 0.01:
            errors.append(
                f"refund_amount {values['refund_amount']:.2f} exceeds the net value of "
                f"the returned quantity ({approved_cap:.2f})"
            )
        other_returns = _fetch_mapping(
            conn,
            """
            SELECT COALESCE(SUM(quantity), 0) AS quantity,
                   COALESCE(SUM(CASE WHEN status = 'approved' THEN refund_amount ELSE 0 END), 0)
                       AS approved_refunds
            FROM returns
            WHERE order_item_id = :order_item_id AND return_id <> :return_id
            """,
            {
                "order_item_id": values["order_item_id"],
                "return_id": values["return_id"],
            },
        )
        if other_returns:
            if other_returns["quantity"] + values["quantity"] > item["quantity"]:
                errors.append(
                    f"return quantity {values['quantity']} plus existing returns "
                    f"({other_returns['quantity']}) exceeds purchased quantity {item['quantity']}"
                )
            refunds = float(other_returns["approved_refunds"])
            if values["status"] == "approved":
                refunds += float(values["refund_amount"])
            if refunds > line_net + 0.005:
                errors.append(
                    f"total approved refunds ({refunds:.2f}) would exceed line net sales "
                    f"({line_net:.2f})"
                )

    existing = _fetch_mapping(
        conn,
        "SELECT * FROM returns WHERE return_id = :return_id",
        {"return_id": values["return_id"]},
    )
    if existing is not None and existing["order_item_id"] != values["order_item_id"]:
        errors.append("order_item_id is immutable for an existing return")
    if errors:
        return errors, None

    fields = ("return_date", "quantity", "refund_amount", "reason", "status")
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO returns (
                    return_id, order_item_id, return_date, quantity, refund_amount,
                    reason, status
                ) VALUES (
                    :return_id, :order_item_id, :return_date, :quantity,
                    :refund_amount, :reason, :status
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE returns
                SET return_date = :return_date, quantity = :quantity,
                    refund_amount = :refund_amount, reason = :reason, status = :status
                WHERE return_id = :return_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


def _process_payment(conn: Connection, values: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    order = _fetch_mapping(
        conn,
        """
        SELECT o.order_id, o.order_date, o.status, vf.net_sales
        FROM orders o
        JOIN v_order_financials vf ON vf.order_id = o.order_id
        WHERE o.order_id = :order_id
        """,
        {"order_id": values["order_id"]},
    )
    if order is None:
        errors.append(f"unknown order_id {values['order_id']!r}")
    else:
        if order["status"] == "cancelled":
            errors.append("payments cannot be recorded for cancelled orders")
        if round_money(abs(float(order["net_sales"]) - float(values["amount"]))) > 0.01:
            errors.append(
                f"payment amount {float(values['amount']):.2f} does not match order net "
                f"sales {float(order['net_sales']):.2f}"
            )
        if order["status"] == "completed" and values["status"] != "paid":
            errors.append("a completed order requires a paid payment")
        if order["status"] == "pending" and values["status"] not in {"pending", "paid"}:
            errors.append("a pending order payment must be pending or paid")
        if values["paid_at"] and values["paid_at"] < order["order_date"]:
            errors.append(f"paid_at {values['paid_at']} is before order_date {order['order_date']}")
    existing = _fetch_mapping(
        conn,
        "SELECT * FROM payments WHERE payment_id = :payment_id",
        {"payment_id": values["payment_id"]},
    )
    other_for_order = _fetch_mapping(
        conn,
        """
        SELECT payment_id FROM payments
        WHERE order_id = :order_id AND payment_id <> :payment_id
        """,
        {"order_id": values["order_id"], "payment_id": values["payment_id"]},
    )
    if other_for_order:
        errors.append(
            f"order {values['order_id']!r} already has payment {other_for_order['payment_id']!r}"
        )
    if existing is not None and existing["order_id"] != values["order_id"]:
        errors.append("order_id is immutable for an existing payment")
    if errors:
        return errors, None

    fields = ("method", "amount", "status", "paid_at")
    if existing is None:
        conn.execute(
            text(
                """
                INSERT INTO payments (
                    payment_id, order_id, method, amount, status, paid_at
                ) VALUES (
                    :payment_id, :order_id, :method, :amount, :status, :paid_at
                )
                """
            ),
            values,
        )
        return [], "inserted"
    if _diff(existing, values, fields):
        conn.execute(
            text(
                """
                UPDATE payments
                SET method = :method, amount = :amount, status = :status,
                    paid_at = :paid_at
                WHERE payment_id = :payment_id
                """
            ),
            values,
        )
        return [], "updated"
    return [], "unchanged"


# ---------------------------------------------------------------------------
# Import audit queries
# ---------------------------------------------------------------------------


def get_import_history(engine: Engine, *, limit: int = 100) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql_query(
            text(
                """
                SELECT import_id, dataset, source_file, status, started_at,
                       completed_at, total_rows, inserted_rows, updated_rows,
                       unchanged_rows, rejected_rows, error_message
                FROM import_batches
                ORDER BY started_at DESC, import_id DESC
                LIMIT :limit
                """
            ),
            conn,
            params={"limit": limit},
        )


def get_import_batch(engine: Engine, import_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM import_batches WHERE import_id = :import_id"),
                {"import_id": import_id},
            )
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


def get_last_import(
    engine: Engine, *, statuses: tuple[str, ...] = ("success", "partial")
) -> dict[str, Any] | None:
    placeholders = ", ".join(f":s{i}" for i in range(len(statuses)))
    params = {f"s{i}": status for i, status in enumerate(statuses)}
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    f"""
                    SELECT * FROM import_batches
                    WHERE status IN ({placeholders})
                    ORDER BY completed_at DESC, started_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


def get_rejection_report(engine: Engine, *, import_id: str | None = None) -> pd.DataFrame:
    params: dict[str, Any] = {}
    condition = ""
    if import_id:
        condition = "WHERE rr.import_id = :import_id"
        params["import_id"] = import_id
    with engine.connect() as conn:
        return pd.read_sql_query(
            text(
                f"""
                SELECT rr.rejection_id, rr.import_id, rr.dataset, rr.row_number,
                       rr.reasons, rr.raw_data, b.source_file, b.started_at
                FROM rejected_records rr
                JOIN import_batches b ON b.import_id = rr.import_id
                {condition}
                ORDER BY b.started_at DESC, rr.import_id DESC, rr.row_number
                """
            ),
            conn,
            params=params,
        )


def get_rejection_reason_counts(engine: Engine) -> pd.DataFrame:
    """Aggregate the first reason phrase per rejection for a compact summary."""
    report = get_rejection_report(engine)
    if report.empty:
        return pd.DataFrame(columns=["reason", "rejections"])
    first_reason = report["reasons"].astype(str).str.split("; ").str[0]
    counts = (
        first_reason.value_counts()
        .rename_axis("reason")
        .reset_index(name="rejections")
        .sort_values(["rejections", "reason"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return counts


def get_import_totals(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS batches,
                           COALESCE(SUM(total_rows), 0) AS processed_rows,
                           COALESCE(SUM(rejected_rows), 0) AS rejected_rows
                    FROM import_batches
                    WHERE status IN ('success', 'partial')
                    """
                )
            )
            .mappings()
            .one()
        )
    return {key: int(value) for key, value in dict(row).items()}


def replay_import_error(exc: DBAPIError) -> bool:
    """Small helper used by tests to distinguish constraint failures."""
    return "constraint" in str(exc).lower() or "abort" in str(exc).lower()


def import_summary_json(summary: ImportSummary) -> str:
    return json.dumps(summary.to_dict(), indent=2, sort_keys=True, default=str)


__all__ = [
    "EXPECTED_COLUMNS",
    "DATASET_KEY",
    "ImportSummary",
    "detect_dataset",
    "get_import_batch",
    "get_import_history",
    "get_import_totals",
    "get_last_import",
    "get_rejection_reason_counts",
    "get_rejection_report",
    "import_summary_json",
    "ingest_file",
]
