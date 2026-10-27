"""Transactional ingestion, audit, and idempotency tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import salespulse.ingestion as ingestion
from salespulse.database import create_db_engine, initialize_database, table_counts
from salespulse.exceptions import ImportExecutionError, InputFileError, SchemaError
from salespulse.ingestion import (
    detect_dataset,
    get_import_history,
    get_import_totals,
    get_last_import,
    get_rejection_reason_counts,
    get_rejection_report,
    ingest_file,
)
from salespulse.schema import INGESTION_ORDER
from salespulse.synthetic_data import DATASET_FILENAMES, expected_messy_rejections


def _fresh_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "ingest.db")
    initialize_database(engine)
    return engine


def _ingest_all(engine, directory: Path) -> None:
    for dataset in INGESTION_ORDER:
        ingest_file(engine, directory / DATASET_FILENAMES[dataset], dataset)


def test_clean_ingestion_loads_every_row(clean_engine, raw_data) -> None:
    _root, manifest = raw_data
    counts = table_counts(clean_engine)
    expected = manifest["clean"]["row_counts"]
    for dataset, count in expected.items():
        assert counts[dataset] == count


def test_reingestion_is_idempotent(clean_engine, raw_data) -> None:
    root, manifest = raw_data
    before = {
        name: count
        for name, count in table_counts(clean_engine).items()
        if name not in {"import_batches", "rejected_records"}
    }
    for dataset in INGESTION_ORDER:
        summary = ingest_file(
            clean_engine,
            root / "clean" / DATASET_FILENAMES[dataset],
            dataset,
        )
        assert summary.status == "success"
        assert summary.inserted_rows == 0
        assert summary.updated_rows == 0
        assert summary.unchanged_rows == summary.total_rows
        assert summary.rejected_rows == 0
    after = {
        name: count
        for name, count in table_counts(clean_engine).items()
        if name not in {"import_batches", "rejected_records"}
    }
    assert after == before
    history = get_import_history(clean_engine, limit=100)
    assert len(history) == 12
    assert set(history["status"]) == {"success"}


def test_messy_import_rejects_only_documented_rows(messy_engine, raw_data) -> None:
    _root, manifest = raw_data
    engine, summaries = messy_engine
    for dataset in INGESTION_ORDER:
        summary = summaries[dataset]
        assert summary.rejected_rows == expected_messy_rejections(dataset)
        assert summary.total_rows == manifest["messy"]["row_counts"][dataset]
        assert summary.status == "partial"

    counts = table_counts(engine)
    accepted_new_customers = 1
    assert (
        counts["customers"] == manifest["clean"]["row_counts"]["customers"] + accepted_new_customers
    )
    for dataset in ("products", "orders", "order_items", "returns", "payments"):
        assert counts[dataset] == manifest["clean"]["row_counts"][dataset]
    assert get_import_totals(engine)["rejected_rows"] == sum(
        expected_messy_rejections(dataset) for dataset in INGESTION_ORDER
    )


def test_rejection_records_are_queryable(messy_engine) -> None:
    engine, _summaries = messy_engine
    report = get_rejection_report(engine)
    assert not report.empty
    assert set(report["dataset"]) == set(INGESTION_ORDER)
    assert report["reasons"].map(lambda value: isinstance(value, str) and value).all()
    assert report["raw_data"].map(lambda value: json.loads(value)).all()
    reasons = get_rejection_reason_counts(engine)
    assert not reasons.empty
    assert reasons["rejections"].sum() == len(report)


def test_dry_run_does_not_persist_business_or_audit_rows(raw_data, tmp_path: Path) -> None:
    root, _manifest = raw_data
    engine = _fresh_engine(tmp_path)
    summary = ingest_file(
        engine,
        root / "clean" / DATASET_FILENAMES["customers"],
        "customers",
        dry_run=True,
    )
    assert summary.dry_run is True
    assert summary.inserted_rows == summary.total_rows
    assert table_counts(engine)["customers"] == 0
    history = get_import_history(engine)
    assert history.empty
    assert get_last_import(engine) is None


def test_messy_dry_run_reports_issues_without_writing(raw_data, tmp_path: Path) -> None:
    root, _manifest = raw_data
    engine = _fresh_engine(tmp_path)
    _ingest_all(engine, root / "clean")
    before = table_counts(engine)
    for dataset in INGESTION_ORDER:
        summary = ingest_file(
            engine,
            root / "messy" / DATASET_FILENAMES[dataset],
            dataset,
            dry_run=True,
        )
        assert summary.rejected_rows == expected_messy_rejections(dataset)
    assert table_counts(engine) == before
    assert len(get_import_history(engine)) == len(INGESTION_ORDER)


def test_schema_failure_is_logged_and_raises(raw_data, tmp_path: Path) -> None:
    root, _manifest = raw_data
    engine = _fresh_engine(tmp_path)
    bad = tmp_path / "customers.csv"
    bad.write_text("customer_id,first_name\nCUST-0001,Ada\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="missing columns"):
        ingest_file(engine, bad, "customers")
    last = get_last_import(engine, statuses=("failed",))
    assert last is not None
    assert last["status"] == "failed"
    assert "missing columns" in last["error_message"]
    assert table_counts(engine)["customers"] == 0


def test_empty_file_is_rejected_and_audited(raw_data, tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    empty = tmp_path / "customers.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(InputFileError, match="empty"):
        ingest_file(engine, empty, "customers")
    history = get_import_history(engine)
    assert len(history) == 1
    assert history.iloc[0]["status"] == "failed"
    assert history.iloc[0]["total_rows"] == 0


def test_unexpected_failure_rolls_back_and_logs_batch(raw_data, tmp_path, monkeypatch) -> None:
    root, _manifest = raw_data
    engine = _fresh_engine(tmp_path)
    ingest_file(engine, root / "clean" / DATASET_FILENAMES["customers"], "customers")

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated processor failure")

    monkeypatch.setattr(ingestion, "_process_product", explode)
    with pytest.raises(ImportExecutionError, match="rolled back"):
        ingest_file(engine, root / "clean" / DATASET_FILENAMES["products"], "products")

    assert table_counts(engine)["products"] == 0
    failed = get_import_history(engine)
    failed = failed[failed["status"] == "failed"]
    assert len(failed) == 1
    assert "simulated processor failure" in failed.iloc[0]["error_message"]


def test_detect_dataset_and_unsupported_dataset(raw_data) -> None:
    root, _manifest = raw_data
    path = root / "clean" / "orders.csv"
    assert detect_dataset(path) == "orders"
    with pytest.raises(SchemaError, match="Could not detect"):
        detect_dataset(root / "clean" / "mystery.csv")


def test_business_rule_violation_is_a_rejection_not_a_crash(raw_data, tmp_path: Path) -> None:
    root, _manifest = raw_data
    engine = _fresh_engine(tmp_path)
    ingest_file(engine, root / "clean" / DATASET_FILENAMES["customers"], "customers")
    ingest_file(engine, root / "clean" / DATASET_FILENAMES["products"], "products")
    import pandas as pd

    orders = pd.read_csv(root / "clean" / DATASET_FILENAMES["orders"], dtype=str).iloc[[0]]
    orders.loc[orders.index[0], "customer_id"] = "CUST-9999"
    path = tmp_path / "orders.csv"
    orders.to_csv(path, index=False, lineterminator="\n")
    summary = ingest_file(engine, path, "orders")
    assert summary.rejected_rows == 1
    assert "unknown customer_id" in summary.rejections[0]["reasons"]
    assert table_counts(engine)["orders"] == 0
