"""Raw-file profiling for the dashboard's upload-and-preview workflow."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from salespulse.exceptions import InputFileError
from salespulse.schema import EXPECTED_COLUMNS
from salespulse.validation import MAX_FILE_BYTES

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INTEGER = re.compile(r"^-?\d+$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


@dataclass(slots=True)
class FileProfile:
    frame: pd.DataFrame
    summary: dict[str, Any]
    columns: pd.DataFrame
    missing_columns: list[str]
    unexpected_columns: list[str]
    required_columns: list[str]


def _infer_type(series: pd.Series) -> str:
    values = [str(value).strip() for value in series.tolist() if str(value).strip() != ""]
    if not values:
        return "empty"
    sample = values[:500]
    if all(_INTEGER.match(value) for value in sample):
        return "integer"
    if all(_INTEGER.match(value) or _DECIMAL.match(value) for value in sample):
        return "decimal"
    if all(_ISO_DATE.match(value) for value in sample):
        return "date"
    return "text"


def profile_frame(frame: pd.DataFrame, dataset: str) -> FileProfile:
    expected = list(EXPECTED_COLUMNS.get(dataset, frame.columns))
    actual = [str(column) for column in frame.columns]
    missing = [column for column in expected if column not in actual]
    unexpected = [column for column in actual if column not in expected]
    missing_cells = int(frame.isna().sum().sum()) + int(
        (frame.astype(str).apply(lambda col: col.str.strip() == "")).sum().sum()
    )
    duplicate_rows = int(frame.duplicated(keep=False).sum())
    column_rows: list[dict[str, Any]] = []
    for column in frame.columns:
        series = frame[column]
        blank = series.astype(str).str.strip().eq("")
        missing_count = int(blank.sum()) + int(series.isna().sum())
        non_null = len(series) - missing_count
        example = ""
        non_blank_values = series[~blank]
        if not non_blank_values.empty:
            example = str(non_blank_values.iloc[0])[:80]
        column_rows.append(
            {
                "column": str(column),
                "inferred_type": _infer_type(series),
                "non_null": non_null,
                "missing": missing_count,
                "missing_pct": round(100.0 * missing_count / max(len(series), 1), 2),
                "unique_values": int(series.nunique(dropna=True)),
                "example": example,
            }
        )
    summary = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing_cells": missing_cells,
        "duplicate_rows": duplicate_rows,
        "fully_blank_rows": int(
            frame.astype(str).apply(lambda row: row.str.strip().eq("").all(), axis=1).sum()
        ),
        "dataset": dataset,
        "expected_columns": len(expected),
        "actual_columns": len(frame.columns),
    }
    return FileProfile(
        frame=frame,
        summary=summary,
        columns=pd.DataFrame(column_rows),
        missing_columns=missing,
        unexpected_columns=unexpected,
        required_columns=expected,
    )


def read_csv_bytes(data: bytes, *, filename: str = "upload.csv") -> pd.DataFrame:
    if not data:
        raise InputFileError("The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise InputFileError(
            f"The uploaded file is {len(data) / 1024 / 1024:.1f} MB; "
            f"the limit is {MAX_FILE_BYTES / 1024 / 1024:.0f} MB."
        )
    try:
        return pd.read_csv(
            io.BytesIO(data),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except pd.errors.EmptyDataError as exc:
        raise InputFileError(f"{filename} has no header or data.") from exc
    except UnicodeDecodeError as exc:
        raise InputFileError(f"{filename} is not valid UTF-8: {exc}") from exc
    except pd.errors.ParserError as exc:
        raise InputFileError(f"{filename} could not be parsed as CSV: {exc}") from exc


def profile_file(path: str | Path, dataset: str) -> FileProfile:
    frame = pd.read_csv(
        Path(path),
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    return profile_frame(frame, dataset)
