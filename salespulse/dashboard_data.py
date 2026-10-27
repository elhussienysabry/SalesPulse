"""Presentation-independent helpers used by the Streamlit dashboard."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from salespulse.exceptions import ReportError
from salespulse.quality import quality_summary


def to_iso_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ReportError(f"Invalid date {value!r}; expected YYYY-MM-DD") from exc


def validated_date_range(
    date_from: str | date,
    date_to: str | date,
    *,
    data_min: str | date | None = None,
    data_max: str | date | None = None,
) -> tuple[str, str]:
    start = to_iso_date(date_from)
    end = to_iso_date(date_to)
    if start > end:
        raise ReportError("The start date must be on or before the end date.")
    if data_min is not None and data_max is not None:
        min_iso = to_iso_date(data_min)
        max_iso = to_iso_date(data_max)
        if end < min_iso or start > max_iso:
            # Out-of-range filters are allowed and produce an explicit empty state.
            return start, end
    return start, end


def format_currency(value: Any, *, currency: str = "$") -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{currency}{float(value):,.2f}"


def format_number(value: Any, *, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    if decimals:
        return f"{float(value):,.{decimals}f}"
    return f"{int(round(float(value))):,}"


def format_pct(value: Any, *, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{decimals}f}%"


def overview_cards(
    overview: pd.DataFrame,
    rates: pd.DataFrame | None = None,
) -> list[dict[str, str]]:
    if overview.empty:
        return [
            {"label": "Net revenue", "value": "$0.00", "help": "No data in range"},
            {"label": "Completed orders", "value": "0", "help": "No data in range"},
            {"label": "Average order value", "value": "$0.00", "help": "No data in range"},
            {"label": "Unique customers", "value": "0", "help": "No data in range"},
            {"label": "Cancellation rate", "value": "—", "help": "No data in range"},
            {"label": "Return rate", "value": "—", "help": "No data in range"},
        ]
    row = overview.iloc[0]
    cancellation_rate = None
    return_rate = None
    if rates is not None and not rates.empty:
        cancellation_rate = rates.iloc[0].get("cancellation_rate_pct")
        return_rate = rates.iloc[0].get("return_rate_pct")
    return [
        {
            "label": "Net revenue",
            "value": format_currency(row.get("net_revenue")),
            "help": "Gross sales − discounts − approved refunds, completed orders only",
        },
        {
            "label": "Completed orders",
            "value": format_number(row.get("completed_orders")),
            "help": "Orders with status = completed in the selected period",
        },
        {
            "label": "Average order value",
            "value": format_currency(row.get("average_order_value")),
            "help": "Net revenue ÷ completed orders",
        },
        {
            "label": "Unique customers",
            "value": format_number(row.get("unique_customers")),
            "help": "Distinct customers with completed orders",
        },
        {
            "label": "Cancellation rate",
            "value": format_pct(cancellation_rate),
            "help": "Cancelled orders ÷ all placed orders in the selected period",
        },
        {
            "label": "Return rate",
            "value": format_pct(return_rate),
            "help": "Approved returned units ÷ units sold on completed orders",
        },
    ]


def quality_cards(checks: pd.DataFrame) -> list[dict[str, str]]:
    summary = quality_summary(checks)
    return [
        {
            "label": "Quality status",
            "value": "PASS" if summary["status"] == "pass" else "REVIEW",
            "help": f"{summary['passed']} of {summary['checks']} checks pass",
        },
        {
            "label": "Critical failures",
            "value": str(summary["critical_failures"]),
            "help": "Critical checks that need investigation before reporting",
        },
        {
            "label": "Warnings",
            "value": str(summary["warning_failures"]),
            "help": "Non-blocking checks worth reviewing",
        },
    ]


def spending_histogram(customer_summary: pd.DataFrame) -> pd.DataFrame:
    if customer_summary.empty or "net_revenue" not in customer_summary:
        return pd.DataFrame(columns=["spend_band", "customers"])
    bands = [0, 100, 250, 500, 1000, 2500, float("inf")]
    labels = ["$0–100", "$100–250", "$250–500", "$500–1k", "$1k–2.5k", "$2.5k+"]
    cut = pd.cut(
        customer_summary["net_revenue"].astype(float),
        bins=bands,
        labels=labels,
        include_lowest=True,
        right=False,
    )
    counts = cut.value_counts().reindex(labels, fill_value=0)
    return pd.DataFrame({"spend_band": labels, "customers": counts.to_numpy()})


def latest_import_rows(history: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    if history.empty:
        return history
    return history.head(limit).copy()


def import_status_label(status: str) -> str:
    return {
        "success": "Success",
        "partial": "Partial — rows rejected",
        "failed": "Failed — rolled back",
        "processing": "Processing",
    }.get(status, status.title())


def quality_failure_frame(checks: pd.DataFrame) -> pd.DataFrame:
    if checks.empty:
        return checks
    return checks[checks["status"] == "fail"].reset_index(drop=True)
