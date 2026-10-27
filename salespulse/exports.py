"""CSV and formatted Excel exports for SalesPulse reports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from salespulse.quality import quality_summary
from salespulse.reporting import ReportBundle

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_ILLEGAL_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_ILLEGAL_FILENAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")

BRAND_NAVY = "0F2742"
BRAND_TEAL = "14B8A6"
LIGHT_TEAL = "E6F7F5"
LIGHT_RED = "FDE8E8"
LIGHT_AMBER = "FFF7E6"
WHITE = "FFFFFF"
GREY = "6B7280"


def sanitize_spreadsheet_value(value: Any) -> Any:
    """Prevent spreadsheet formula injection while preserving numbers."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if not isinstance(value, str):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def sanitize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if output[column].dtype == object:
            output[column] = output[column].map(sanitize_spreadsheet_value)
    return output


def _safe_sheet_title(name: str, existing: set[str]) -> str:
    clean = _ILLEGAL_SHEET_CHARS.sub(" ", name).strip() or "Sheet"
    clean = re.sub(r"\s+", " ", clean)[:31]
    candidate = clean
    suffix = 2
    while candidate.casefold() in existing:
        suffix_text = f" ({suffix})"
        candidate = f"{clean[: 31 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    existing.add(candidate.casefold())
    return candidate


def _column_width(frame: pd.DataFrame, column: str, values: list[Any]) -> float:
    header_length = len(str(column))
    longest = 0
    for value in values[:1000]:
        if value is None:
            continue
        longest = max(longest, len(str(value)))
    width = max(header_length + 2, min(longest + 2, 46))
    if column in {"raw_data", "reasons", "detail", "recommended_action"}:
        width = 60
    return float(width)


def _write_readme(
    workbook: Workbook,
    bundle: ReportBundle,
    sheet_rows: list[tuple[str, int]],
) -> None:
    ws = workbook.active
    ws.title = "Read Me"
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:D1")
    ws["A1"] = "SalesPulse — Sales Performance Report"
    ws["A1"].font = Font(size=18, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=BRAND_NAVY)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 34
    ws["A2"] = "Synthetic demonstration data — no real customer or business data"
    ws["A2"].font = Font(size=10, italic=True, color=GREY)
    ws.merge_cells("A2:D2")

    overview = bundle.section("Overview")
    kpis: list[tuple[str, Any]] = []
    if not overview.empty:
        row = overview.iloc[0]
        kpis = [
            ("Completed orders", int(row["completed_orders"])),
            ("Net revenue (USD)", float(row["net_revenue"])),
            ("Gross sales (USD)", float(row["gross_sales"])),
            ("Discounts (USD)", float(row["discounts"])),
            ("Approved refunds (USD)", float(row["refunds"])),
            ("Average order value (USD)", float(row["average_order_value"])),
            ("Unique purchasing customers", int(row["unique_customers"])),
        ]
    quality = quality_summary(bundle.section("Data Quality"))

    metadata_rows: list[tuple[str, Any]] = [
        ("Generated at (UTC)", bundle.generated_at),
        ("Period from", bundle.date_from),
        ("Period to", bundle.date_to),
        ("Category filter", bundle.metadata.get("category_filter", "All categories")),
        ("Reporting currency", "USD"),
        ("Data source", bundle.metadata.get("data_source", "Synthetic data")),
        (
            "Data quality",
            f"{quality['status'].upper()} — {quality['passed']}/{quality['checks']} checks pass",
        ),
        ("Revenue definition", bundle.metadata.get("revenue_definition", "")),
        ("Synthetic notice", bundle.metadata.get("synthetic_notice", "")),
    ]
    row_number = 4
    ws.cell(row=row_number, column=1, value="Report information").font = Font(
        bold=True, size=12, color=BRAND_NAVY
    )
    row_number += 1
    for label, value in metadata_rows:
        ws.cell(row=row_number, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=row_number, column=2, value=sanitize_spreadsheet_value(value))
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=4)
        row_number += 1

    row_number += 1
    ws.cell(row=row_number, column=1, value="Headline KPIs").font = Font(
        bold=True, size=12, color=BRAND_NAVY
    )
    row_number += 1
    for label, value in kpis:
        ws.cell(row=row_number, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=row_number, column=2, value=value)
        cell.number_format = "#,##0" if isinstance(value, int) else "#,##0.00"
        row_number += 1

    row_number += 1
    ws.cell(row=row_number, column=1, value="Workbook contents").font = Font(
        bold=True, size=12, color=BRAND_NAVY
    )
    row_number += 1
    ws.cell(row=row_number, column=1, value="Sheet").font = Font(bold=True, color=WHITE)
    ws.cell(row=row_number, column=2, value="Rows").font = Font(bold=True, color=WHITE)
    ws.cell(row=row_number, column=3, value="Data source / purpose").font = Font(
        bold=True, color=WHITE
    )
    for col in range(1, 4):
        ws.cell(row=row_number, column=col).fill = PatternFill("solid", fgColor=BRAND_NAVY)
    row_number += 1
    for sheet_name, count in sheet_rows:
        ws.cell(row=row_number, column=1, value=sheet_name)
        ws.cell(row=row_number, column=2, value=count)
        ws.cell(
            row=row_number,
            column=3,
            value="Calculated from the SalesPulse SQLite database via documented SQL queries.",
        )
        row_number += 1

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 62
    ws.column_dimensions["D"].width = 28
    ws.freeze_panes = "A4"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True


def _write_data_sheet(
    workbook: Workbook,
    name: str,
    frame: pd.DataFrame,
    *,
    bundle: ReportBundle,
    existing_titles: set[str],
) -> str:
    title = _safe_sheet_title(name, existing_titles)
    ws = workbook.create_sheet(title)
    safe = sanitize_frame(frame)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(frame.columns), 1))
    ws.cell(row=1, column=1, value=name)
    ws.cell(row=1, column=1).font = Font(size=14, bold=True, color=WHITE)
    ws.cell(row=1, column=1).fill = PatternFill("solid", fgColor=BRAND_NAVY)
    ws.row_dimensions[1].height = 24
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(len(frame.columns), 1))
    ws.cell(
        row=2,
        column=1,
        value=(
            f"{bundle.title} | {bundle.date_from} to {bundle.date_to} | "
            f"{bundle.metadata.get('category_filter', 'All categories')} | "
            "Synthetic data"
        ),
    )
    ws.cell(row=2, column=1).font = Font(size=9, italic=True, color=GREY)

    header_fill = PatternFill("solid", fgColor=BRAND_TEAL)
    header_font = Font(bold=True, color=WHITE)
    thin_border = Border(bottom=Side(style="thin", color="D1D5DB"))
    for column_index, column in enumerate(frame.columns, start=1):
        cell = ws.cell(row=4, column=column_index, value=str(column))
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[4].height = 28

    if frame.empty:
        ws.merge_cells(
            start_row=5, start_column=1, end_row=5, end_column=max(len(frame.columns), 1)
        )
        ws.cell(row=5, column=1, value="No data matches the selected filters.")
        ws.cell(row=5, column=1).font = Font(italic=True, color=GREY)
    else:
        for row_offset, (_, row) in enumerate(safe.iterrows(), start=5):
            for column_index, column in enumerate(frame.columns, start=1):
                raw_value = row[column]
                if isinstance(raw_value, float) and math.isnan(raw_value):
                    raw_value = None
                if raw_value is pd.NA:
                    raw_value = None
                if isinstance(raw_value, str) and len(raw_value) > 32_000:
                    raw_value = raw_value[:32_000] + "…"
                cell = ws.cell(row=row_offset, column=column_index, value=raw_value)
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=column
                    in {"raw_data", "reasons", "detail", "recommended_action", "error_message"},
                )
                if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
                    cell.number_format = "#,##0" if isinstance(raw_value, int) else "#,##0.00"

    if name == "Data Quality" and not frame.empty:
        status_index = list(frame.columns).index("status") + 1
        for row_offset in range(5, 5 + len(frame)):
            status_cell = ws.cell(row=row_offset, column=status_index)
            if status_cell.value == "fail":
                for column_index in range(1, len(frame.columns) + 1):
                    ws.cell(row=row_offset, column=column_index).fill = PatternFill(
                        "solid", fgColor=LIGHT_RED
                    )

    for column_index, column in enumerate(frame.columns, start=1):
        values = safe[column].tolist() if not frame.empty else []
        ws.column_dimensions[get_column_letter(column_index)].width = _column_width(
            frame, str(column), values
        )
    if not frame.empty:
        ws.auto_filter.ref = f"A4:{get_column_letter(len(frame.columns))}{4 + len(frame)}"
    ws.freeze_panes = "A5"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:4"
    ws.print_options.horizontalCentered = True
    return title


def export_bundle_to_excel(bundle: ReportBundle, output_path: str | Path) -> Path:
    """Write a styled multi-sheet workbook; returns the output path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    existing_titles: set[str] = set()
    sheet_rows: list[tuple[str, int]] = []
    sheet_frames: list[tuple[str, pd.DataFrame]] = []
    for name, frame in bundle.sections.items():
        title = _safe_sheet_title(name, existing_titles)
        sheet_rows.append((title, len(frame)))
        sheet_frames.append((title, frame))

    # Read Me is written first because it is the active sheet; contents are
    # based on the final ordered sections. Sheet titles are reserved above.
    workbook.active.title = "Read Me"
    existing_titles.add("read me")
    _write_readme(workbook, bundle, sheet_rows)
    written: set[str] = {"read me"}
    for name, frame in bundle.sections.items():
        _write_data_sheet(
            workbook,
            name,
            frame,
            bundle=bundle,
            existing_titles=written,
        )

    workbook.properties.title = bundle.title
    workbook.properties.subject = "SalesPulse automated analytics report"
    workbook.properties.creator = "SalesPulse"
    workbook.properties.description = (
        "Synthetic demonstration data. Generated from the SalesPulse SQLite database."
    )
    workbook.save(path)
    return path


def _slugify(value: str) -> str:
    slug = _ILLEGAL_FILENAME_CHARS.sub("_", value.strip()).strip("_").lower()
    return slug or "section"


def export_bundle_to_csv(bundle: ReportBundle, output_dir: str | Path) -> Path:
    """Write one UTF-8 CSV per report section plus a metadata manifest."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for index, (name, frame) in enumerate(bundle.sections.items(), start=1):
        filename = f"{index:02d}_{_slugify(name)}.csv"
        path = directory / filename
        sanitize_frame(frame).to_csv(path, index=False, lineterminator="\n")
        files.append(
            {
                "section": name,
                "filename": filename,
                "rows": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "title": bundle.title,
        "date_from": bundle.date_from,
        "date_to": bundle.date_to,
        "generated_at": bundle.generated_at,
        "synthetic": True,
        "synthetic_notice": bundle.metadata.get("synthetic_notice"),
        "data_source": bundle.metadata.get("data_source"),
        "category_filter": bundle.metadata.get("category_filter"),
        "revenue_definition": bundle.metadata.get("revenue_definition"),
        "files": files,
    }
    (directory / "report_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return directory


def export_quality_csv(bundle: ReportBundle, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitize_frame(bundle.section("Data Quality")).to_csv(path, index=False, lineterminator="\n")
    return path
