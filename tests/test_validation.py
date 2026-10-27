"""Static validation and label-normalization tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from salespulse.exceptions import InputFileError, SchemaError
from salespulse.synthetic_data import generate_clean_data
from salespulse.validation import read_source_csv, validate_dataset, validate_schema

AS_OF = date(2026, 10, 27)


@pytest.fixture(scope="module")
def sample():
    return generate_clean_data(seed=42, customer_count=20, product_count=6, order_count=20)


def _single(frame: pd.DataFrame, **changes: object) -> pd.DataFrame:
    row = frame.iloc[[0]].copy().astype(object)
    for column, value in changes.items():
        row.loc[row.index[0], column] = value
    return row


def test_clean_rows_validate_without_rejections(sample) -> None:
    for dataset in ("customers", "products", "orders", "order_items", "returns", "payments"):
        outcome = validate_dataset(sample[dataset], dataset, as_of_date=AS_OF)
        assert outcome.rejected_count == 0
        assert outcome.valid_count == len(sample[dataset])


def test_normalizable_aliases_are_accepted(sample) -> None:
    customers = validate_dataset(
        _single(sample["customers"], region="  NORTH   AMERICA "),
        "customers",
        as_of_date=AS_OF,
    )
    assert customers.rejected_count == 0
    assert customers.valid_rows.iloc[0]["region"] == "North America"

    products = validate_dataset(
        _single(sample["products"], category="home and kitchen"),
        "products",
        as_of_date=AS_OF,
    )
    assert products.rejected_count == 0
    assert products.valid_rows.iloc[0]["category"] == "Home & Kitchen"

    orders = validate_dataset(
        _single(sample["orders"], status="Complete"), "orders", as_of_date=AS_OF
    )
    assert orders.rejected_count == 0
    assert orders.valid_rows.iloc[0]["status"] == "completed"

    returns = validate_dataset(
        _single(sample["returns"], status="Approved", refund_amount="0.00"),
        "returns",
        as_of_date=AS_OF,
    )
    assert returns.rejected_count == 0
    assert returns.valid_rows.iloc[0]["status"] == "approved"

    payments = validate_dataset(
        _single(sample["payments"], method="Credit Card", status="Settled"),
        "payments",
        as_of_date=AS_OF,
    )
    assert payments.rejected_count == 0
    assert payments.valid_rows.iloc[0]["method"] == "card"
    assert payments.valid_rows.iloc[0]["status"] == "paid"


def test_label_normalization_can_be_disabled(sample) -> None:
    outcome = validate_dataset(
        _single(sample["customers"], region="APAC"),
        "customers",
        as_of_date=AS_OF,
        normalize_labels=False,
    )
    assert outcome.rejected_count == 1
    assert "unsupported value" in " ".join(outcome.rejections[0].reasons)


def test_invalid_rows_are_rejected_with_useful_reasons(sample) -> None:
    frame = pd.concat(
        [
            _single(sample["customers"], email="not-an-email"),
            _single(sample["customers"], signup_date="2026-02-30"),
            _single(sample["customers"], region="Mars"),
        ],
        ignore_index=True,
    )
    outcome = validate_dataset(frame, "customers", as_of_date=AS_OF)
    assert outcome.rejected_count == 3
    reasons = " | ".join(" ".join(item.reasons) for item in outcome.rejections)
    assert "invalid email" in reasons
    assert "not a valid calendar date" in reasons
    assert "unsupported value" in reasons


def test_duplicate_ids_and_emails_are_rejected(sample) -> None:
    row = _single(sample["customers"])
    frame = pd.concat([row, row], ignore_index=True)
    outcome = validate_dataset(frame, "customers", as_of_date=AS_OF)
    assert outcome.rejected_count == 1
    reasons = " ".join(outcome.rejections[0].reasons)
    assert "duplicate customer_id" in reasons
    assert "duplicate email" in reasons


def test_future_dates_are_rejected(sample) -> None:
    outcome = validate_dataset(
        _single(sample["orders"], order_date="2099-01-01"),
        "orders",
        as_of_date=AS_OF,
    )
    assert outcome.rejected_count == 1
    assert "future" in " ".join(outcome.rejections[0].reasons)


def test_schema_validation_reorders_and_rejects_mismatches(sample) -> None:
    frame = sample["products"].iloc[[0]][list(reversed(sample["products"].columns))]
    ordered = validate_schema(frame, "products")
    assert list(ordered.columns) == list(sample["products"].columns)

    with pytest.raises(SchemaError, match="missing columns"):
        validate_schema(sample["products"].drop(columns=["category"]), "products")
    with pytest.raises(SchemaError, match="unexpected columns"):
        validate_schema(sample["products"].assign(extra=1), "products")
    with pytest.raises(SchemaError, match="Unknown dataset"):
        validate_schema(sample["products"], "unknown")


def test_read_source_csv_guards_empty_and_missing_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(InputFileError, match="not found"):
        read_source_csv(missing)

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(InputFileError, match="empty"):
        read_source_csv(empty)

    header_only = tmp_path / "header.csv"
    header_only.write_text("customer_id,first_name\n", encoding="utf-8")
    with pytest.raises(InputFileError, match="no data rows"):
        read_source_csv(header_only)


def test_reader_handles_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "customers.csv"
    path.write_text("\ufeffcustomer_id,first_name\nCUST-0001,Ada\n", encoding="utf-8")
    frame = read_source_csv(path)
    assert list(frame.columns) == ["customer_id", "first_name"]
    assert frame.iloc[0]["first_name"] == "Ada"
