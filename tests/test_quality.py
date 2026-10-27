"""Data-quality and reconciliation check tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import text

from salespulse.database import create_db_engine, database_integrity, get_schema_version
from salespulse.quality import quality_checks_csv, quality_summary, run_quality_checks


def test_all_checks_pass_on_clean_data(clean_engine) -> None:
    checks = run_quality_checks(clean_engine)
    summary = quality_summary(checks)
    assert len(checks) == 25
    assert set(checks.columns) == {
        "checked_at",
        "check_name",
        "severity",
        "failures",
        "status",
        "detail",
        "recommended_action",
    }
    assert summary == {
        "checks": 25,
        "passed": 25,
        "failed": 0,
        "critical_failures": 0,
        "warning_failures": 0,
        "failure_rows": 0,
        "status": "pass",
    }
    assert checks["recommended_action"].map(bool).all()
    exported = quality_checks_csv(clean_engine)
    assert list(exported.columns) == list(checks.columns)
    assert len(exported) == len(checks)


def test_quality_passes_after_rejected_messy_rows_are_quarantined(messy_engine) -> None:
    engine, _summaries = messy_engine
    summary = quality_summary(run_quality_checks(engine))
    assert summary["critical_failures"] == 0
    assert summary["status"] == "pass"


def test_integrity_helpers(clean_engine) -> None:
    integrity = database_integrity(clean_engine)
    assert integrity["quick_check"] == "ok"
    assert integrity["foreign_key_violations"] == 0
    assert get_schema_version(clean_engine) == "1.0.0"


def test_tampered_payment_is_detected(clean_engine, tmp_path: Path) -> None:
    copy_path = tmp_path / "tampered.db"
    shutil.copy2(clean_engine.url.database, copy_path)
    engine = create_db_engine(copy_path)
    with engine.begin() as conn:
        payment = conn.execute(
            text("SELECT payment_id FROM payments WHERE status = 'paid' LIMIT 1")
        ).scalar_one()
        conn.execute(
            text("UPDATE payments SET amount = 1.00 WHERE payment_id = :payment_id"),
            {"payment_id": payment},
        )
    checks = run_quality_checks(engine)
    summary = quality_summary(checks)
    assert summary["critical_failures"] >= 1
    failed = checks[checks["status"] == "fail"]
    assert "payment_amount_mismatch" in set(failed["check_name"])


def test_future_dated_order_is_a_warning(clean_engine, tmp_path: Path) -> None:
    copy_path = tmp_path / "future.db"
    shutil.copy2(clean_engine.url.database, copy_path)
    engine = create_db_engine(copy_path)
    with engine.begin() as conn:
        order = conn.execute(text("SELECT order_id FROM orders LIMIT 1")).scalar_one()
        conn.execute(
            text("UPDATE orders SET order_date = '2099-01-01' WHERE order_id = :order_id"),
            {"order_id": order},
        )
    checks = run_quality_checks(engine)
    failed = checks[checks["status"] == "fail"]
    assert "orders_future_dated" in set(failed["check_name"])
    summary = quality_summary(checks)
    assert summary["warning_failures"] >= 1
