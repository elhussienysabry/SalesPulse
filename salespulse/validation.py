"""Source-file schema checks, row normalization, and static validation.

The validation layer is deliberately explicit. It trims whitespace and maps a
documented set of categorical aliases; anything else that does not meet the
contract is rejected with a reason rather than silently repaired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from salespulse.exceptions import InputFileError, SchemaError
from salespulse.schema import DATASET_KEY, EXPECTED_COLUMNS
from salespulse.transformations import (
    CATEGORIES,
    CATEGORY_ALIASES,
    ORDER_STATUS_ALIASES,
    ORDER_STATUSES,
    PAYMENT_METHOD_ALIASES,
    PAYMENT_METHODS,
    PAYMENT_STATUS_ALIASES,
    PAYMENT_STATUSES,
    REGION_ALIASES,
    REGIONS,
    RETURN_REASON_ALIASES,
    RETURN_REASONS,
    RETURN_STATUS_ALIASES,
    RETURN_STATUSES,
    canonicalize,
    clean_text,
    normalize_email,
    parse_boolean,
    parse_decimal,
    parse_integer,
)

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_REASON_LENGTH = 500
MAX_RAW_DATA_LENGTH = 4000
MAX_REASONS_PER_ROW = 8

ID_PATTERNS = {
    "customers": re.compile(r"^CUST-\d{4}$"),
    "products": re.compile(r"^PROD-\d{3}$"),
    "orders": re.compile(r"^ORD-\d{5}$"),
    "order_items": re.compile(r"^OI-\d{7}$"),
    "returns": re.compile(r"^RET-\d{5}$"),
    "payments": re.compile(r"^PAY-ORD-\d{5}$"),
}

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "customers": (
        "customer_id",
        "first_name",
        "last_name",
        "email",
        "signup_date",
        "region",
        "country",
        "city",
    ),
    "products": (
        "product_id",
        "product_name",
        "category",
        "unit_price",
        "unit_cost",
        "launch_date",
        "is_active",
    ),
    "orders": (
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "shipping_region",
        "shipping_country",
        "shipping_city",
    ),
    "order_items": (
        "order_item_id",
        "order_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount_rate",
    ),
    "returns": (
        "return_id",
        "order_item_id",
        "return_date",
        "quantity",
        "refund_amount",
        "reason",
        "status",
    ),
    "payments": ("payment_id", "order_id", "method", "amount", "status"),
}

SUPPORTED_DATASETS = tuple(EXPECTED_COLUMNS)


@dataclass(slots=True)
class RowRejection:
    row_number: int
    raw_data: dict[str, Any]
    reasons: list[str]

    def as_record(self, dataset: str, import_id: str) -> dict[str, Any]:
        import json

        raw = json.dumps(self.raw_data, ensure_ascii=False, default=str)
        return {
            "import_id": import_id,
            "dataset": dataset,
            "row_number": self.row_number,
            "raw_data": raw[:MAX_RAW_DATA_LENGTH],
            "reasons": "; ".join(self.reasons)[:2000],
        }


@dataclass(slots=True)
class ValidationOutcome:
    dataset: str
    total_rows: int
    valid_rows: pd.DataFrame
    rejections: list[RowRejection] = field(default_factory=list)
    valid_row_numbers: list[int] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)


def read_source_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV as text and enforce file-level safety/schema rules."""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise InputFileError(f"Input file not found: {file_path}")
    size = file_path.stat().st_size
    if size == 0:
        raise InputFileError(f"Input file is empty: {file_path.name}")
    if size > MAX_FILE_BYTES:
        raise InputFileError(
            f"Input file is {size / 1024 / 1024:.1f} MB; the limit is "
            f"{MAX_FILE_BYTES / 1024 / 1024:.0f} MB"
        )
    try:
        frame = pd.read_csv(
            file_path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except UnicodeDecodeError as exc:
        raise InputFileError(f"{file_path.name} is not valid UTF-8: {exc}") from exc
    except pd.errors.EmptyDataError as exc:
        raise InputFileError(f"{file_path.name} has no header or data") from exc
    except pd.errors.ParserError as exc:
        raise InputFileError(f"{file_path.name} could not be parsed as CSV: {exc}") from exc

    if len(frame.index) == 0:
        raise InputFileError(f"{file_path.name} contains a header but no data rows")
    return frame


def validate_schema(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Check expected columns and return them in canonical order."""
    if dataset not in EXPECTED_COLUMNS:
        raise SchemaError(
            f"Unknown dataset {dataset!r}; supported datasets: {', '.join(SUPPORTED_DATASETS)}"
        )
    expected = list(EXPECTED_COLUMNS[dataset])
    actual = [str(column) for column in frame.columns]
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected columns: {', '.join(unexpected)}")
        raise SchemaError(
            f"Schema mismatch for dataset {dataset!r}: {'; '.join(details)}. "
            f"Expected columns: {', '.join(expected)}"
        )
    return frame.loc[:, expected].copy()


def _parse_date(
    value: object,
    *,
    field_name: str,
    as_of: date,
    required: bool = True,
) -> tuple[str | None, str | None]:
    raw = clean_text(value)
    if not raw:
        if required:
            return None, f"missing required field {field_name!r}"
        return None, None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None, f"{field_name} must be an ISO date (YYYY-MM-DD), got {raw!r}"
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None, f"{field_name} is not a valid calendar date: {raw!r}"
    if parsed > as_of:
        return None, f"{field_name} {raw} is in the future (as of {as_of.isoformat()})"
    if parsed.year < 2000:
        return None, f"{field_name} {raw} is before the supported range (2000-01-01)"
    return parsed.isoformat(), None


def _check_id(value: object, dataset: str) -> tuple[str | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, f"missing required field {DATASET_KEY[dataset]!r}"
    if not ID_PATTERNS[dataset].fullmatch(raw):
        return None, (
            f"{DATASET_KEY[dataset]} has invalid format {raw!r}; "
            f"expected pattern {ID_PATTERNS[dataset].pattern}"
        )
    return raw, None


def _check_text(
    value: object,
    *,
    field_name: str,
    required: bool = True,
    max_length: int = 120,
) -> tuple[str | None, str | None]:
    raw = clean_text(value)
    if not raw:
        if required:
            return None, f"missing required field {field_name!r}"
        return None, None
    if len(raw) > max_length:
        return None, f"{field_name} exceeds {max_length} characters"
    return raw, None


def _categorical(
    value: object,
    *,
    field_name: str,
    aliases: dict[str, str],
    allowed: tuple[str, ...],
    normalize_labels: bool,
) -> tuple[str | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, f"missing required field {field_name!r}"
    if normalize_labels:
        canonical, error = canonicalize(raw, aliases, allowed)
    else:
        canonical = raw if raw in allowed else None
        error = (
            None
            if canonical
            else f"unsupported value {raw!r}; expected one of: {', '.join(allowed)}"
        )
    if error:
        return None, f"{field_name}: {error}"
    return canonical, None


def _base_rejections(frame: pd.DataFrame) -> list[RowRejection]:
    # Preserve the original CSV row number: header is line 1.
    return [
        RowRejection(row_number=index + 2, raw_data=row.to_dict(), reasons=[])
        for index, row in frame.iterrows()
    ]


def _finalize_rejections(rejections: list[RowRejection]) -> list[RowRejection]:
    output: list[RowRejection] = []
    for rejection in rejections:
        if not rejection.reasons:
            continue
        reasons = rejection.reasons[:MAX_REASONS_PER_ROW]
        rejection.reasons = [reason[:MAX_REASON_LENGTH] for reason in reasons]
        output.append(rejection)
    return output


def _validate_customers(
    frame: pd.DataFrame,
    *,
    as_of: date,
    normalize_labels: bool,
) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    seen_emails: dict[str, int] = {}
    for position, (_index, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        customer_id, error = _check_id(row["customer_id"], "customers")
        if error:
            rejection.reasons.append(error)
        else:
            values["customer_id"] = customer_id
        for field_name in ("first_name", "last_name"):
            text, error = _check_text(row[field_name], field_name=field_name)
            if error:
                rejection.reasons.append(error)
            else:
                values[field_name] = text
        email, error = normalize_email(row["email"])
        if error:
            rejection.reasons.append(f"email: {error}")
        else:
            values["email"] = email
        signup, error = _parse_date(row["signup_date"], field_name="signup_date", as_of=as_of)
        if error:
            rejection.reasons.append(error)
        else:
            values["signup_date"] = signup
        region, error = _categorical(
            row["region"],
            field_name="region",
            aliases=REGION_ALIASES,
            allowed=REGIONS,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["region"] = region
        for field_name in ("country", "city"):
            text, error = _check_text(row[field_name], field_name=field_name)
            if error:
                rejection.reasons.append(error)
            else:
                values[field_name] = text

        if not rejection.reasons:
            assert customer_id is not None
            if customer_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate customer_id {customer_id!r} in file "
                    f"(first seen on row {seen_ids[customer_id]})"
                )
            if values["email"] in seen_emails:
                rejection.reasons.append(
                    f"duplicate email {values['email']!r} in file "
                    f"(first seen on row {seen_emails[values['email']]})"
                )
            if not rejection.reasons:
                seen_ids[customer_id] = rejection.row_number
                seen_emails[values["email"]] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="customers",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["customers"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def _validate_products(
    frame: pd.DataFrame,
    *,
    as_of: date,
    normalize_labels: bool,
) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    for position, (_, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        product_id, error = _check_id(row["product_id"], "products")
        if error:
            rejection.reasons.append(error)
        else:
            values["product_id"] = product_id
        name, error = _check_text(row["product_name"], field_name="product_name")
        if error:
            rejection.reasons.append(error)
        else:
            values["product_name"] = name
        category, error = _categorical(
            row["category"],
            field_name="category",
            aliases=CATEGORY_ALIASES,
            allowed=CATEGORIES,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["category"] = category
        price, error = parse_decimal(
            row["unit_price"],
            field_name="unit_price",
            minimum=0.01,
            maximum=100_000,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["unit_price"] = price
        cost, error = parse_decimal(
            row["unit_cost"],
            field_name="unit_cost",
            minimum=0,
            maximum=100_000,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["unit_cost"] = cost
        launch, error = _parse_date(row["launch_date"], field_name="launch_date", as_of=as_of)
        if error:
            rejection.reasons.append(error)
        else:
            values["launch_date"] = launch
        active, error = parse_boolean(row["is_active"])
        if error:
            rejection.reasons.append(error)
        else:
            values["is_active"] = active
        if (
            values.get("unit_price") is not None
            and values.get("unit_cost") is not None
            and float(values["unit_cost"]) > float(values["unit_price"])
        ):
            rejection.reasons.append("unit_cost must be less than or equal to unit_price")
        if not rejection.reasons:
            assert product_id is not None
            if product_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate product_id {product_id!r} in file "
                    f"(first seen on row {seen_ids[product_id]})"
                )
            else:
                seen_ids[product_id] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="products",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["products"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def _validate_orders(
    frame: pd.DataFrame,
    *,
    as_of: date,
    normalize_labels: bool,
) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    for position, (_, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        order_id, error = _check_id(row["order_id"], "orders")
        if error:
            rejection.reasons.append(error)
        else:
            values["order_id"] = order_id
        customer_id, error = _check_id(row["customer_id"], "customers")
        if error:
            rejection.reasons.append(f"customer_id: {error.replace('customer_id ', '')}")
        else:
            values["customer_id"] = customer_id
        order_date, error = _parse_date(row["order_date"], field_name="order_date", as_of=as_of)
        if error:
            rejection.reasons.append(error)
        else:
            values["order_date"] = order_date
        status, error = _categorical(
            row["status"],
            field_name="status",
            aliases=ORDER_STATUS_ALIASES,
            allowed=ORDER_STATUSES,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["status"] = status
        region, error = _categorical(
            row["shipping_region"],
            field_name="shipping_region",
            aliases=REGION_ALIASES,
            allowed=REGIONS,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["shipping_region"] = region
        for field_name in ("shipping_country", "shipping_city"):
            text, error = _check_text(row[field_name], field_name=field_name)
            if error:
                rejection.reasons.append(error)
            else:
                values[field_name] = text
        if not rejection.reasons:
            assert order_id is not None
            if order_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate order_id {order_id!r} in file "
                    f"(first seen on row {seen_ids[order_id]})"
                )
            else:
                seen_ids[order_id] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="orders",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["orders"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def _validate_order_items(frame: pd.DataFrame) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    seen_pairs: dict[tuple[str, str], int] = {}
    for position, (_, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        item_id, error = _check_id(row["order_item_id"], "order_items")
        if error:
            rejection.reasons.append(error)
        else:
            values["order_item_id"] = item_id
        order_id, error = _check_id(row["order_id"], "orders")
        if error:
            rejection.reasons.append(f"order_id: {error.replace('order_id ', '')}")
        else:
            values["order_id"] = order_id
        product_id, error = _check_id(row["product_id"], "products")
        if error:
            rejection.reasons.append(f"product_id: {error.replace('product_id ', '')}")
        else:
            values["product_id"] = product_id
        quantity, error = parse_integer(
            row["quantity"], field_name="quantity", minimum=1, maximum=1000
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["quantity"] = quantity
        price, error = parse_decimal(
            row["unit_price"], field_name="unit_price", minimum=0.01, maximum=100_000
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["unit_price"] = price
        discount, error = parse_decimal(
            row["discount_rate"],
            field_name="discount_rate",
            minimum=0,
            maximum=0.9,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["discount_rate"] = discount
        if not rejection.reasons:
            assert item_id is not None and order_id is not None and product_id is not None
            if item_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate order_item_id {item_id!r} in file "
                    f"(first seen on row {seen_ids[item_id]})"
                )
            pair = (order_id, product_id)
            if pair in seen_pairs:
                rejection.reasons.append(
                    f"duplicate (order_id, product_id) {pair} in file "
                    f"(first seen on row {seen_pairs[pair]})"
                )
            if not rejection.reasons:
                seen_ids[item_id] = rejection.row_number
                seen_pairs[pair] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="order_items",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["order_items"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def _validate_returns(
    frame: pd.DataFrame,
    *,
    as_of: date,
    normalize_labels: bool,
) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    for position, (_, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        return_id, error = _check_id(row["return_id"], "returns")
        if error:
            rejection.reasons.append(error)
        else:
            values["return_id"] = return_id
        item_id, error = _check_id(row["order_item_id"], "order_items")
        if error:
            rejection.reasons.append(f"order_item_id: {error.replace('order_item_id ', '')}")
        else:
            values["order_item_id"] = item_id
        return_date, error = _parse_date(row["return_date"], field_name="return_date", as_of=as_of)
        if error:
            rejection.reasons.append(error)
        else:
            values["return_date"] = return_date
        quantity, error = parse_integer(
            row["quantity"], field_name="quantity", minimum=1, maximum=1000
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["quantity"] = quantity
        refund, error = parse_decimal(
            row["refund_amount"], field_name="refund_amount", minimum=0, maximum=100_000
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["refund_amount"] = refund
        reason, error = _categorical(
            row["reason"],
            field_name="reason",
            aliases=RETURN_REASON_ALIASES,
            allowed=RETURN_REASONS,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["reason"] = reason
        status, error = _categorical(
            row["status"],
            field_name="status",
            aliases=RETURN_STATUS_ALIASES,
            allowed=RETURN_STATUSES,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["status"] = status
        if not rejection.reasons:
            assert return_id is not None
            if return_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate return_id {return_id!r} in file "
                    f"(first seen on row {seen_ids[return_id]})"
                )
            else:
                seen_ids[return_id] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="returns",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["returns"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def _validate_payments(
    frame: pd.DataFrame,
    *,
    as_of: date,
    normalize_labels: bool,
) -> ValidationOutcome:
    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    rejections = _base_rejections(frame)
    seen_ids: dict[str, int] = {}
    seen_orders: dict[str, int] = {}
    for position, (_, row) in enumerate(frame.iterrows()):
        rejection = rejections[position]
        values: dict[str, Any] = {}
        payment_id, error = _check_id(row["payment_id"], "payments")
        if error:
            rejection.reasons.append(error)
        else:
            values["payment_id"] = payment_id
        order_id, error = _check_id(row["order_id"], "orders")
        if error:
            rejection.reasons.append(f"order_id: {error.replace('order_id ', '')}")
        else:
            values["order_id"] = order_id
        method, error = _categorical(
            row["method"],
            field_name="method",
            aliases=PAYMENT_METHOD_ALIASES,
            allowed=PAYMENT_METHODS,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["method"] = method
        amount, error = parse_decimal(
            row["amount"], field_name="amount", minimum=0, maximum=10_000_000
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["amount"] = amount
        status, error = _categorical(
            row["status"],
            field_name="status",
            aliases=PAYMENT_STATUS_ALIASES,
            allowed=PAYMENT_STATUSES,
            normalize_labels=normalize_labels,
        )
        if error:
            rejection.reasons.append(error)
        else:
            values["status"] = status
        paid_at, error = _parse_date(
            row.get("paid_at", ""),
            field_name="paid_at",
            as_of=as_of,
            required=False,
        )
        if error:
            rejection.reasons.append(error)
        elif paid_at is not None:
            values["paid_at"] = paid_at
        else:
            values["paid_at"] = None
        if not rejection.reasons:
            if values["status"] == "paid" and not values["paid_at"]:
                rejection.reasons.append("paid_at is required when payment status is 'paid'")
            if values["status"] in {"pending", "failed"} and values["paid_at"]:
                rejection.reasons.append("paid_at must be empty unless payment status is 'paid'")
            assert payment_id is not None
            if payment_id in seen_ids:
                rejection.reasons.append(
                    f"duplicate payment_id {payment_id!r} in file "
                    f"(first seen on row {seen_ids[payment_id]})"
                )
            if values["order_id"] in seen_orders:
                rejection.reasons.append(
                    f"duplicate payment for order_id {values['order_id']!r} in file "
                    f"(first seen on row {seen_orders[values['order_id']]})"
                )
            if not rejection.reasons:
                seen_ids[payment_id] = rejection.row_number
                seen_orders[values["order_id"]] = rejection.row_number
                rows.append(values)
                row_numbers.append(rejection.row_number)
    return ValidationOutcome(
        dataset="payments",
        total_rows=len(frame),
        valid_rows=pd.DataFrame(rows, columns=EXPECTED_COLUMNS["payments"]),
        rejections=_finalize_rejections(rejections),
        valid_row_numbers=row_numbers,
    )


def validate_dataset(
    frame: pd.DataFrame,
    dataset: str,
    *,
    as_of_date: date | None = None,
    normalize_labels: bool = True,
) -> ValidationOutcome:
    """Validate and normalize all rows of a dataset without touching the DB."""
    frame = validate_schema(frame, dataset)
    as_of = as_of_date or date.today()
    if dataset == "customers":
        return _validate_customers(frame, as_of=as_of, normalize_labels=normalize_labels)
    if dataset == "products":
        return _validate_products(frame, as_of=as_of, normalize_labels=normalize_labels)
    if dataset == "orders":
        return _validate_orders(frame, as_of=as_of, normalize_labels=normalize_labels)
    if dataset == "order_items":
        return _validate_order_items(frame)
    if dataset == "returns":
        return _validate_returns(frame, as_of=as_of, normalize_labels=normalize_labels)
    if dataset == "payments":
        return _validate_payments(frame, as_of=as_of, normalize_labels=normalize_labels)
    raise SchemaError(f"Unsupported dataset {dataset!r}")


def validate_file(
    path: str | Path,
    dataset: str,
    *,
    as_of_date: date | None = None,
    normalize_labels: bool = True,
) -> ValidationOutcome:
    frame = read_source_csv(path)
    return validate_dataset(
        frame, dataset, as_of_date=as_of_date, normalize_labels=normalize_labels
    )
