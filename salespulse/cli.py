"""SalesPulse command-line workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import date
from pathlib import Path

from sqlalchemy import Engine

from salespulse.analytics import AnalyticsService
from salespulse.config import DEFAULT_SEED, PROJECT_ROOT, Settings
from salespulse.database import (
    create_db_engine,
    get_schema_version,
    initialize_database,
    require_initialized,
    table_counts,
)
from salespulse.exceptions import SalesPulseError
from salespulse.exports import export_bundle_to_csv, export_bundle_to_excel
from salespulse.ingestion import (
    ImportSummary,
    detect_dataset,
    get_import_history,
    ingest_file,
)
from salespulse.quality import quality_summary, run_quality_checks
from salespulse.reporting import format_report_text, generate_report, write_markdown_report
from salespulse.schema import INGESTION_ORDER
from salespulse.synthetic_data import DATASET_FILENAMES, write_all_datasets


def _relative(path: str | Path, settings: Settings) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return path.name


def _load_engine(settings: Settings, *, initialize: bool = False) -> Engine:
    settings.ensure_directories()
    engine = create_db_engine(settings.db_path)
    if initialize:
        initialize_database(engine)
    else:
        require_initialized(engine)
    return engine


def _print_import_summary(summary: ImportSummary) -> None:
    suffix = " (dry run — rolled back)" if summary.dry_run else ""
    print(
        f"[{summary.dataset}] {summary.status.upper()}{suffix} | "
        f"file={summary.source_file} | total={summary.total_rows} | "
        f"inserted={summary.inserted_rows} updated={summary.updated_rows} "
        f"unchanged={summary.unchanged_rows} rejected={summary.rejected_rows}"
    )
    if summary.rejections:
        for shown, rejection in enumerate(summary.rejections):
            if shown >= 5:
                remaining = len(summary.rejections) - shown
                print(f"  ... and {remaining} more rejected rows; see the rejection report")
                break
            print(f"  row {rejection['row_number']}: {rejection['reasons']}")


def _write_json(path: str | Path, payload: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def _resolve_report_dates(
    engine: Engine, date_from: str | None, date_to: str | None
) -> tuple[str, str]:
    if (date_from is None) != (date_to is None):
        raise SalesPulseError("Provide both --from and --to, or neither to use the data range.")
    if date_from and date_to:
        return date_from, date_to
    bounds = AnalyticsService(engine).date_bounds()
    if bounds is None:
        raise SalesPulseError("No orders exist. Run seed-data and ingest-all first.")
    return bounds


def _command_init_db(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_directories()
    engine = create_db_engine(settings.db_path)
    initialize_database(engine)
    version = get_schema_version(engine)
    print(f"Database ready: {_relative(settings.db_path, settings)} (schema {version})")
    counts = table_counts(engine)
    print(
        "Business row counts: "
        + ", ".join(
            f"{name}={counts[name]}"
            for name in ("customers", "products", "orders", "order_items", "returns", "payments")
        )
    )
    return 0


def _command_seed_data(args: argparse.Namespace, settings: Settings) -> int:
    raw_dir = Path(args.out).expanduser().resolve() if args.out else settings.raw_dir
    existing = [raw_dir / "clean" / name for name in DATASET_FILENAMES.values()]
    if any(path.exists() for path in existing) and not args.force:
        raise SalesPulseError(
            f"Sample data already exists in {_relative(raw_dir, settings)}. "
            "Use --force to regenerate it."
        )
    manifest = write_all_datasets(
        raw_dir,
        seed=args.seed,
        customer_count=args.customers,
        product_count=args.products,
        order_count=args.orders,
    )
    clean_counts = manifest["clean"]["row_counts"]
    messy_counts = manifest["messy"]["row_counts"]
    print(
        f"Generated deterministic sample data (seed={args.seed}) in {_relative(raw_dir, settings)}"
    )
    print("Clean: " + ", ".join(f"{name}={count}" for name, count in clean_counts.items()))
    print("Messy: " + ", ".join(f"{name}={count}" for name, count in messy_counts.items()))
    print("All records are fictional. Every file is reproducible from the seed and data version.")
    return 0


def _ingest_one(
    engine: Engine,
    path: Path,
    args: argparse.Namespace,
) -> ImportSummary:
    dataset = args.dataset or detect_dataset(path)
    summary = ingest_file(
        engine,
        path,
        dataset,
        normalize_labels=not getattr(args, "no_normalize_labels", False),
        as_of_date=args.as_of_date,
        dry_run=getattr(args, "dry_run", False),
    )
    _print_import_summary(summary)
    return summary


def _write_optional_summary(path: str | None, summaries: list[ImportSummary]) -> None:
    if not path:
        return
    payload = {
        "generated_at": summaries[0].started_at if summaries else None,
        "imports": [summary.to_dict() for summary in summaries],
        "totals": {
            "processed": sum(summary.total_rows for summary in summaries),
            "inserted": sum(summary.inserted_rows for summary in summaries),
            "updated": sum(summary.updated_rows for summary in summaries),
            "unchanged": sum(summary.unchanged_rows for summary in summaries),
            "rejected": sum(summary.rejected_rows for summary in summaries),
        },
    }
    target = _write_json(path, payload)
    print(f"Machine-readable import summary: {target}")


def _command_ingest(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    path = Path(args.path)
    summary = _ingest_one(engine, path, args)
    if args.summary_json:
        _write_optional_summary(args.summary_json, [summary])
    return 0


def _command_ingest_all(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    directory = Path(args.dir)
    if not directory.exists():
        raise SalesPulseError(f"Data directory not found: {directory}")
    summaries: list[ImportSummary] = []
    failures: list[tuple[str, str]] = []
    for dataset in INGESTION_ORDER:
        path = directory / DATASET_FILENAMES[dataset]
        if not path.exists():
            print(f"[{dataset}] skipped — {path.name} not found")
            continue
        try:
            summary = ingest_file(
                engine,
                path,
                dataset,
                normalize_labels=not args.no_normalize_labels,
                as_of_date=args.as_of_date,
            )
            _print_import_summary(summary)
            summaries.append(summary)
        except SalesPulseError as exc:
            print(f"[{dataset}] FAILED: {exc}", file=sys.stderr)
            failures.append((dataset, str(exc)))
    if not summaries and not failures:
        raise SalesPulseError(f"No supported CSV files found in {directory}")
    _write_optional_summary(args.summary_json, summaries)
    if failures:
        raise SalesPulseError(
            f"{len(failures)} dataset import(s) failed: " + ", ".join(name for name, _ in failures)
        )
    print(
        f"Ingested {len(summaries)} dataset(s) safely; "
        f"processed {sum(item.total_rows for item in summaries)} rows."
    )
    return 0


def _command_report(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    date_from, date_to = _resolve_report_dates(engine, args.date_from, args.date_to)
    bundle = generate_report(
        engine,
        date_from,
        date_to,
        category=args.category,
        top_limit=args.limit,
    )
    print(format_report_text(bundle, max_rows=args.max_rows))
    if args.markdown:
        path = write_markdown_report(bundle, args.markdown)
        print(f"Markdown report written: {_relative(path, settings)}")
    return 0


def _command_export(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    date_from, date_to = _resolve_report_dates(engine, args.date_from, args.date_to)
    bundle = generate_report(
        engine,
        date_from,
        date_to,
        category=args.category,
        top_limit=args.limit,
    )
    fmt = args.format.lower()
    if args.output:
        output = Path(args.output)
    elif fmt == "xlsx":
        output = settings.output_dir / f"sales_report_{date_from}_{date_to}.xlsx"
    else:
        output = settings.output_dir / f"csv_{date_from}_{date_to}"
    if fmt == "xlsx":
        path = export_bundle_to_excel(bundle, output)
        print(f"Excel report written: {_relative(path, settings)}")
    elif fmt == "csv":
        path = export_bundle_to_csv(bundle, output)
        print(f"CSV report sections written: {_relative(path, settings)}/")
        print(f"Files: {len(bundle.sections)} CSV sections + report_manifest.json")
    else:
        raise SalesPulseError("--format must be 'xlsx' or 'csv'")
    return 0


def _command_quality(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    checks = run_quality_checks(engine)
    summary = quality_summary(checks)
    print(
        f"Data quality: {summary['status'].upper()} | checks={summary['checks']} "
        f"passed={summary['passed']} failed={summary['failed']} "
        f"critical_failures={summary['critical_failures']} "
        f"warnings={summary['warning_failures']}"
    )
    failed = checks[checks["status"] == "fail"]
    if failed.empty:
        print("All checks pass.")
    else:
        print(failed[["check_name", "severity", "failures", "detail"]].to_string(index=False))
    if args.export:
        path = Path(args.export)
        path.parent.mkdir(parents=True, exist_ok=True)
        checks.to_csv(path, index=False, lineterminator="\n")
        print(f"Quality report written: {_relative(path, settings)}")
    return 0 if summary["critical_failures"] == 0 else 1


def _command_import_history(args: argparse.Namespace, settings: Settings) -> int:
    engine = _load_engine(settings)
    history = get_import_history(engine, limit=args.limit)
    if history.empty:
        print("No imports have been recorded yet.")
        return 0
    if args.json:
        print(json.dumps(history.to_dict(orient="records"), indent=2, default=str))
    else:
        print(history.to_string(index=False))
    return 0


def _command_demo(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_directories()
    if args.reset and settings.db_path.exists():
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = Path(str(settings.db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        print(f"Removed existing database: {_relative(settings.db_path, settings)}")
    engine = _load_engine(settings, initialize=True)
    print(f"Database: {_relative(settings.db_path, settings)}")

    expected_files = [settings.raw_dir / "clean" / name for name in DATASET_FILENAMES.values()]
    if args.regenerate_data or not all(path.exists() for path in expected_files):
        manifest = write_all_datasets(settings.raw_dir, seed=settings.seed)
        print(
            "Generated sample data: "
            + ", ".join(
                f"{name}={count}" for name, count in manifest["clean"]["row_counts"].items()
            )
        )
    else:
        print(f"Using existing sample data in {_relative(settings.raw_dir, settings)}")

    summaries: list[ImportSummary] = []
    for dataset in INGESTION_ORDER:
        path = settings.raw_dir / "clean" / DATASET_FILENAMES[dataset]
        summary = ingest_file(engine, path, dataset, as_of_date=settings.as_of_date)
        _print_import_summary(summary)
        summaries.append(summary)

    if args.with_messy:
        print("\nImporting the deliberately messy dataset to demonstrate rejection handling...")
        for dataset in INGESTION_ORDER:
            path = settings.raw_dir / "messy" / DATASET_FILENAMES[dataset]
            summary = ingest_file(engine, path, dataset, as_of_date=settings.as_of_date)
            _print_import_summary(summary)
            summaries.append(summary)

    _write_optional_summary(str(settings.output_dir / "import_summary.json"), summaries)
    bounds = AnalyticsService(engine).date_bounds()
    if bounds is None:
        raise SalesPulseError("Demo data loaded but no orders were found.")
    bundle = generate_report(engine, bounds[0], bounds[1])
    xlsx_path = export_bundle_to_excel(bundle, settings.output_dir / "sales_report.xlsx")
    csv_dir = export_bundle_to_csv(bundle, settings.output_dir / "csv")
    markdown_path = write_markdown_report(bundle, PROJECT_ROOT / "docs" / "sample_report.md")
    print("\n" + format_report_text(bundle, max_rows=5))
    summary = quality_summary(bundle.section("Data Quality"))
    print("\nExports:")
    print(f"  Excel: {_relative(xlsx_path, settings)}")
    print(f"  CSV:   {_relative(csv_dir, settings)}/")
    print(f"  Markdown sample: {_relative(markdown_path, settings)}")
    print(
        f"\nQuality summary: {summary['status'].upper()} "
        f"({summary['passed']}/{summary['checks']} checks pass, "
        f"{summary['critical_failures']} critical failures)"
    )
    print("\nDemo complete. Start the dashboard with: streamlit run app.py")
    return 0 if summary["critical_failures"] == 0 else 1


def _parse_date_arg(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO date (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m salespulse.cli",
        description=(
            "SalesPulse: deterministic sample data, validated ingestion, SQL analytics, "
            "and CSV/Excel reporting. All demo data is synthetic."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_db_option(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--db",
            help="SQLite database path (default: data/processed/salespulse.db)",
        )

    init_parser = subparsers.add_parser("init-db", help="Create or update the database schema.")
    add_db_option(init_parser)
    init_parser.set_defaults(func=_command_init_db)

    seed_parser = subparsers.add_parser(
        "seed-data", help="Generate deterministic clean and messy CSV datasets."
    )
    seed_parser.add_argument("--out", help="Raw data output directory (default: data/raw).")
    seed_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    seed_parser.add_argument("--customers", type=int, default=200)
    seed_parser.add_argument("--products", type=int, default=42)
    seed_parser.add_argument("--orders", type=int, default=None)
    seed_parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    seed_parser.set_defaults(func=_command_seed_data)

    ingest_parser = subparsers.add_parser("ingest", help="Validate and ingest one CSV file.")
    ingest_parser.add_argument("path")
    ingest_parser.add_argument("--dataset", choices=INGESTION_ORDER)
    ingest_parser.add_argument("--no-normalize-labels", action="store_true")
    ingest_parser.add_argument("--dry-run", action="store_true")
    ingest_parser.add_argument("--as-of-date", type=_parse_date_arg)
    ingest_parser.add_argument("--summary-json")
    add_db_option(ingest_parser)
    ingest_parser.set_defaults(func=_command_ingest)

    all_parser = subparsers.add_parser(
        "ingest-all", help="Ingest all supported CSV files in dependency order."
    )
    all_parser.add_argument("--dir", default=str(PROJECT_ROOT / "data" / "raw" / "clean"))
    all_parser.add_argument("--no-normalize-labels", action="store_true")
    all_parser.add_argument("--as-of-date", type=_parse_date_arg)
    all_parser.add_argument("--summary-json")
    add_db_option(all_parser)
    all_parser.set_defaults(func=_command_ingest_all)

    report_parser = subparsers.add_parser("report", help="Run and print analytical reports.")
    report_parser.add_argument("--from", dest="date_from", help="Inclusive start date (YYYY-MM-DD)")
    report_parser.add_argument("--to", dest="date_to", help="Inclusive end date (YYYY-MM-DD)")
    report_parser.add_argument("--category", help="Optional category filter for product reports")
    report_parser.add_argument("--limit", type=int, default=10, help="Top-N limit (default 10).")
    report_parser.add_argument("--max-rows", type=int, default=12)
    report_parser.add_argument("--markdown", help="Optional path for a Markdown report.")
    add_db_option(report_parser)
    report_parser.set_defaults(func=_command_report)

    export_parser = subparsers.add_parser(
        "export", help="Export all report sections to XLSX or CSV."
    )
    export_parser.add_argument("--format", choices=("xlsx", "csv"), default="xlsx")
    export_parser.add_argument("--output", help="Output .xlsx file or CSV directory.")
    export_parser.add_argument("--from", dest="date_from")
    export_parser.add_argument("--to", dest="date_to")
    export_parser.add_argument("--category")
    export_parser.add_argument("--limit", type=int, default=10)
    add_db_option(export_parser)
    export_parser.set_defaults(func=_command_export)

    quality_parser = subparsers.add_parser("quality", help="Run SQL and database integrity checks.")
    quality_parser.add_argument("--export", help="Optional CSV path for the quality report.")
    add_db_option(quality_parser)
    quality_parser.set_defaults(func=_command_quality)

    history_parser = subparsers.add_parser("import-history", help="Show recorded import batches.")
    history_parser.add_argument("--limit", type=int, default=25)
    history_parser.add_argument("--json", action="store_true")
    add_db_option(history_parser)
    history_parser.set_defaults(func=_command_import_history)

    demo_parser = subparsers.add_parser(
        "demo", help="Run the complete demo: init, seed, ingest, report, export, quality."
    )
    demo_parser.add_argument(
        "--reset", action="store_true", help="Delete the existing SalesPulse DB before running."
    )
    demo_parser.add_argument(
        "--regenerate-data", action="store_true", help="Regenerate the synthetic CSV files."
    )
    demo_parser.add_argument(
        "--with-messy",
        action="store_true",
        help="Also import the messy dataset to demonstrate rejection auditing.",
    )
    add_db_option(demo_parser)
    demo_parser.set_defaults(func=_command_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env(
        db_path=getattr(args, "db", None),
    )
    try:
        return int(args.func(args, settings))
    except SalesPulseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI safety boundary
        print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        if os.getenv("SALESPULSE_DEBUG") == "1":
            traceback.print_exc()
        else:
            print("Set SALESPULSE_DEBUG=1 for a traceback.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
