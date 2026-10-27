"""Application configuration.

Paths are resolved relative to the repository root so the same commands work
from any current directory. Environment variables (optionally loaded from a
local .env file) can override every default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from salespulse.exceptions import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "salespulse.db"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
ANALYTICS_SQL_DIR = PROJECT_ROOT / "sql" / "analytics"
DEFAULT_SEED = 42
DEFAULT_DATA_VERSION = "1.0.0"


def _resolve_path(raw: str, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"SALESPULSE_AS_OF_DATE must be an ISO date (YYYY-MM-DD), got {raw!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime settings."""

    root_dir: Path
    data_dir: Path
    db_path: Path
    output_dir: Path
    seed: int = DEFAULT_SEED
    as_of_date: date | None = None

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def output_path(self) -> Path:
        return self.output_dir

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(
        cls,
        *,
        db_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        load_env_file: bool = True,
    ) -> Settings:
        """Build settings from explicit values and environment fallbacks."""
        if load_env_file:
            load_dotenv(PROJECT_ROOT / ".env", override=False)

        raw_db = str(db_path) if db_path is not None else os.getenv("SALESPULSE_DB_PATH", "")
        raw_data = str(data_dir) if data_dir is not None else os.getenv("SALESPULSE_DATA_DIR", "")
        raw_output = (
            str(output_dir) if output_dir is not None else os.getenv("SALESPULSE_OUTPUT_DIR", "")
        )
        raw_seed = os.getenv("SALESPULSE_SEED", str(DEFAULT_SEED))
        try:
            seed = int(raw_seed)
        except ValueError as exc:
            raise ConfigurationError(
                f"SALESPULSE_SEED must be an integer, got {raw_seed!r}"
            ) from exc
        if seed < 0:
            raise ConfigurationError("SALESPULSE_SEED must be zero or greater")

        resolved_data = _resolve_path(raw_data, PROJECT_ROOT / "data")
        resolved_db = (
            _resolve_path(raw_db, DEFAULT_DB_PATH)
            if raw_db
            else resolved_data / "processed" / "salespulse.db"
        )
        return cls(
            root_dir=PROJECT_ROOT,
            data_dir=resolved_data,
            db_path=resolved_db,
            output_dir=_resolve_path(raw_output, PROJECT_ROOT / "output"),
            seed=seed,
            as_of_date=_parse_iso_date(os.getenv("SALESPULSE_AS_OF_DATE")),
        )
