"""Data-quality reporting: SQL checks plus database-level integrity checks."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import Engine, text

from salespulse.analytics import AnalyticsService
from salespulse.database import database_integrity, get_schema_version, require_initialized

RECOMMENDED_ACTIONS = {
    "approved_refunds_exceed_line_net": (
        "Investigate the return and order-item rows; refunds must not exceed the line value."
    ),
    "completed_orders_without_items": (
        "Add the missing order items or change the order status after review."
    ),
    "date_sequence_errors": (
        "Correct dates only after checking the source system; document the correction."
    ),
    "duplicate_order_events": (
        "Review possible duplicate orders before changing status or recognising revenue."
    ),
    "duplicate_primary_keys": "Deduplicate source records and re-run the import.",
    "duplicate_order_item_business_keys": (
        "Merge duplicate order lines or correct the product reference."
    ),
    "imports_with_failures": "Review the error message in the import audit table.",
    "invalid_quantities_or_prices": "Correct the source values before re-importing.",
    "invalid_statuses": "Map the source status to the documented allow-list.",
    "missing_required_values": "Supply the required values in the source file.",
    "orders_future_dated": "Check the source date and timezone/backfill process.",
    "orphan_order_items": "Import the parent order and product before the line.",
    "orphan_orders": "Import the customer before the order.",
    "orphan_payments": "Import the order before the payment.",
    "orphan_returns": "Import the order item before the return.",
    "payment_amount_mismatch": (
        "Re-import the payment after confirming the order total or investigate the difference."
    ),
    "payments_for_cancelled_orders": "Remove or correct the payment after investigation.",
    "return_quantity_exceeds_purchase": "Correct the return quantity in the source.",
    "returns_on_non_completed_orders": "Review the order status or return record.",
    "revenue_reconciliation_order_vs_line": (
        "Do not use revenue reports until the view definitions and data are reconciled."
    ),
    "revenue_component_reconciliation": (
        "Check discount and refund calculations; do not adjust totals manually."
    ),
    "stuck_import_batches": "Inspect the importer logs and clean up stale processing batches.",
    "foreign_key_integrity": "Fix foreign keys through a reviewed correction import.",
    "database_quick_check": "Run a SQLite backup and integrity investigation immediately.",
    "schema_version": "Run python -m salespulse.cli init-db to restore schema metadata.",
}


def _python_checks(engine: Engine) -> list[dict[str, object]]:
    integrity = database_integrity(engine)
    schema_version = get_schema_version(engine)
    with engine.connect() as conn:
        failed_imports = int(
            conn.execute(
                text("SELECT COUNT(*) FROM import_batches WHERE status = 'failed'")
            ).scalar_one()
        )
        pending_imports = int(
            conn.execute(
                text("SELECT COUNT(*) FROM import_batches WHERE status = 'processing'")
            ).scalar_one()
        )
    return [
        {
            "check_name": "database_quick_check",
            "severity": "critical",
            "failures": 0 if integrity["quick_check"] == "ok" else 1,
            "status": "pass" if integrity["quick_check"] == "ok" else "fail",
            "detail": f"SQLite quick_check returned {integrity['quick_check']!r}.",
        },
        {
            "check_name": "foreign_key_integrity",
            "severity": "critical",
            "failures": int(integrity["foreign_key_violations"]),
            "status": "pass" if integrity["foreign_key_violations"] == 0 else "fail",
            "detail": "PRAGMA foreign_key_check found no violations."
            if integrity["foreign_key_violations"] == 0
            else f"Foreign-key violations: {integrity['foreign_key_details'][:5]}",
        },
        {
            "check_name": "schema_version",
            "severity": "warning",
            "failures": 0 if schema_version else 1,
            "status": "pass" if schema_version else "fail",
            "detail": f"Schema version: {schema_version or 'missing'}.",
        },
        {
            "check_name": "imports_with_failures",
            "severity": "warning",
            "failures": failed_imports,
            "status": "pass" if failed_imports == 0 else "fail",
            "detail": f"Failed import batches: {failed_imports}; processing batches: {pending_imports}.",
        },
    ]


def run_quality_checks(engine: Engine) -> pd.DataFrame:
    """Run all SQL and database integrity checks and return a tidy table."""
    require_initialized(engine)
    service = AnalyticsService(engine)
    sql_checks = service.quality_checks()
    rows = sql_checks.to_dict(orient="records") + _python_checks(engine)
    frame = pd.DataFrame(
        rows,
        columns=["check_name", "severity", "failures", "status", "detail"],
    )
    frame["failures"] = frame["failures"].astype(int)
    frame["recommended_action"] = (
        frame["check_name"]
        .map(RECOMMENDED_ACTIONS)
        .fillna("Review the affected records before making any correction.")
    )
    severity_order = {"critical": 0, "warning": 1}
    frame["_severity_order"] = frame["severity"].map(severity_order)
    frame = frame.sort_values(
        ["status", "_severity_order", "check_name"],
        key=lambda series: (
            series.map({"fail": 0, "pass": 1}) if series.name == "status" else series
        ),
    ).drop(columns="_severity_order")
    frame.reset_index(drop=True, inplace=True)
    frame.insert(0, "checked_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return frame


def quality_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Summarise check results for dashboard cards and CLI output."""
    critical = frame[frame["severity"] == "critical"]
    warnings = frame[frame["severity"] == "warning"]
    return {
        "checks": int(len(frame)),
        "passed": int((frame["status"] == "pass").sum()),
        "failed": int((frame["status"] == "fail").sum()),
        "critical_failures": int((critical["status"] == "fail").sum()),
        "warning_failures": int((warnings["status"] == "fail").sum()),
        "failure_rows": int(frame["failures"].sum()),
        "status": "pass" if (frame["status"] == "fail").sum() == 0 else "fail",
    }


def quality_checks_csv(engine: Engine) -> pd.DataFrame:
    return run_quality_checks(engine)
