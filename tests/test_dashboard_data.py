"""Presentation helpers and upload profiling tests."""

from __future__ import annotations

import pandas as pd
import pytest

from salespulse.dashboard_data import (
    format_currency,
    format_number,
    format_pct,
    import_status_label,
    latest_import_rows,
    overview_cards,
    quality_cards,
    quality_failure_frame,
    spending_histogram,
    to_iso_date,
    validated_date_range,
)
from salespulse.exceptions import InputFileError, ReportError
from salespulse.profiling import profile_frame, read_csv_bytes
from salespulse.quality import run_quality_checks


def test_formatting_helpers_handle_empty_values() -> None:
    assert format_currency(1234.5) == "$1,234.50"
    assert format_currency(None) == "—"
    assert format_number(12345) == "12,345"
    assert format_number(12.345, decimals=2) == "12.35"
    assert format_pct(4.234) == "4.23%"
    assert format_pct(float("nan")) == "—"


def test_date_helpers_validate_and_preserve_ranges() -> None:
    assert to_iso_date("2026-01-02") == "2026-01-02"
    assert validated_date_range("2026-01-01", "2026-01-31") == (
        "2026-01-01",
        "2026-01-31",
    )
    assert validated_date_range(
        "2035-01-01",
        "2035-01-31",
        data_min="2025-01-01",
        data_max="2026-06-30",
    ) == ("2035-01-01", "2035-01-31")
    with pytest.raises(ReportError, match="on or before"):
        validated_date_range("2026-02-01", "2026-01-01")
    with pytest.raises(ReportError, match="Invalid date"):
        to_iso_date("02/01/2026")


def test_overview_cards_for_data_and_empty_state(clean_engine) -> None:
    from salespulse.analytics import AnalyticsService

    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    overview = service.overview_metrics(start, end)
    rates = service.cancellation_and_return_rates(start, end)
    cards = overview_cards(overview, rates)
    assert len(cards) == 6
    assert cards[0]["label"] == "Net revenue"
    assert cards[0]["value"].startswith("$")
    assert cards[4]["value"].endswith("%")
    assert cards[5]["value"].endswith("%")

    empty = overview_cards(pd.DataFrame())
    assert len(empty) == 6
    assert all(card["value"] in {"$0.00", "0", "—"} for card in empty)


def test_quality_cards_and_failure_frame(clean_engine) -> None:
    checks = run_quality_checks(clean_engine)
    cards = quality_cards(checks)
    assert [card["label"] for card in cards] == [
        "Quality status",
        "Critical failures",
        "Warnings",
    ]
    assert cards[0]["value"] == "PASS"
    assert quality_failure_frame(checks).empty


def test_spending_histogram_buckets() -> None:
    frame = pd.DataFrame({"net_revenue": [0, 50, 150, 300, 600, 1500, 3000]})
    histogram = spending_histogram(frame)
    assert histogram["customers"].sum() == len(frame)
    assert histogram["spend_band"].tolist()[0] == "$0–100"
    assert histogram["spend_band"].tolist()[-1] == "$2.5k+"
    assert spending_histogram(pd.DataFrame()).empty


def test_latest_imports_and_status_labels() -> None:
    frame = pd.DataFrame({"x": range(10)})
    assert len(latest_import_rows(frame, limit=3)) == 3
    assert latest_import_rows(pd.DataFrame()).empty
    assert import_status_label("partial").startswith("Partial")
    assert import_status_label("failed").startswith("Failed")
    assert import_status_label("mystery") == "Mystery"


def test_profile_frame_reports_columns_and_missingness() -> None:
    frame = pd.DataFrame(
        {
            "customer_id": ["CUST-0001", "CUST-0001", "", "CUST-0001"],
            "first_name": ["Ada", None, "  ", "Ada"],
            "email": [
                "a@example.test",
                "b@example.test",
                "c@example.test",
                "a@example.test",
            ],
            "extra": ["x", "y", "z", "x"],
        }
    )
    profile = profile_frame(frame, "customers")
    assert profile.summary["rows"] == 4
    assert profile.summary["columns"] == 4
    assert profile.summary["duplicate_rows"] == 2
    assert profile.summary["missing_cells"] == 3
    assert "last_name" in profile.missing_columns
    assert profile.unexpected_columns == ["extra"]
    column = profile.columns.set_index("column")
    assert column.loc["first_name", "missing"] == 2
    assert column.loc["customer_id", "unique_values"] == 2


def test_read_csv_bytes_handles_bom_and_errors() -> None:
    frame = read_csv_bytes("\ufeffcustomer_id,first_name\nCUST-0001,Ada\n".encode())
    assert list(frame.columns) == ["customer_id", "first_name"]
    with pytest.raises(InputFileError, match="empty"):
        read_csv_bytes(b"")
