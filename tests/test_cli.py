"""End-to-end CLI workflow tests using a temporary database and data directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from salespulse.cli import main


def test_full_cli_workflow(tmp_path: Path, capsys) -> None:
    db = tmp_path / "workflow.db"
    raw = tmp_path / "raw"
    assert main(["init-db", "--db", str(db)]) == 0
    assert "Database ready" in capsys.readouterr().out

    assert (
        main(
            [
                "seed-data",
                "--out",
                str(raw),
                "--seed",
                "42",
                "--customers",
                "60",
                "--products",
                "12",
                "--orders",
                "100",
            ]
        )
        == 0
    )
    assert (raw / "clean" / "orders.csv").exists()
    assert (raw / "messy" / "orders.csv").exists()
    capsys.readouterr()

    summary_path = tmp_path / "import_summary.json"
    assert (
        main(
            [
                "ingest-all",
                "--dir",
                str(raw / "clean"),
                "--db",
                str(db),
                "--summary-json",
                str(summary_path),
            ]
        )
        == 0
    )
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["totals"]["processed"] == 60 + 12 + 100 + 196 + 11 + 90
    assert payload["totals"]["rejected"] == 0
    assert all(item["status"] == "success" for item in payload["imports"])
    capsys.readouterr()

    markdown = tmp_path / "report.md"
    assert (
        main(
            [
                "report",
                "--db",
                str(db),
                "--from",
                "2025-01-01",
                "--to",
                "2026-06-30",
                "--markdown",
                str(markdown),
                "--max-rows",
                "2",
            ]
        )
        == 0
    )
    assert markdown.exists()
    assert "SalesPulse" in markdown.read_text(encoding="utf-8")
    capsys.readouterr()

    xlsx = tmp_path / "report.xlsx"
    assert main(["export", "--db", str(db), "--format", "xlsx", "--output", str(xlsx)]) == 0
    assert xlsx.exists()
    capsys.readouterr()

    csv_dir = tmp_path / "csv"
    assert main(["export", "--db", str(db), "--format", "csv", "--output", str(csv_dir)]) == 0
    assert (csv_dir / "report_manifest.json").exists()
    capsys.readouterr()

    quality_csv = tmp_path / "quality.csv"
    assert main(["quality", "--db", str(db), "--export", str(quality_csv)]) == 0
    assert quality_csv.exists()
    assert "Data quality: PASS" in capsys.readouterr().out

    assert main(["import-history", "--db", str(db), "--json", "--limit", "3"]) == 0
    history = json.loads(capsys.readouterr().out)
    assert len(history) == 3
    assert {item["status"] for item in history} == {"success"}


def test_seed_data_requires_force_to_overwrite(tmp_path: Path, capsys) -> None:
    raw = tmp_path / "raw"
    args = [
        "seed-data",
        "--out",
        str(raw),
        "--seed",
        "42",
        "--customers",
        "20",
        "--products",
        "6",
        "--orders",
        "30",
    ]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().err
    assert main([*args, "--force"]) == 0


def test_report_on_empty_database_fails_cleanly(tmp_path: Path, capsys) -> None:
    db = tmp_path / "empty.db"
    assert main(["init-db", "--db", str(db)]) == 0
    capsys.readouterr()
    assert main(["report", "--db", str(db)]) == 1
    assert "No orders exist" in capsys.readouterr().err


def test_unknown_dataset_is_a_clean_error(tmp_path: Path, capsys) -> None:
    db = tmp_path / "x.db"
    assert main(["init-db", "--db", str(db)]) == 0
    bad = tmp_path / "mystery.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert main(["ingest", str(bad), "--db", str(db)]) == 1
    assert "Could not detect dataset" in capsys.readouterr().err


def test_module_entrypoint_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "salespulse.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0
    assert "init-db" in result.stdout
    assert "ingest-all" in result.stdout
    assert "demo" in result.stdout
