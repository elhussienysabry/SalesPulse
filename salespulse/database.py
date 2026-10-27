"""SQLite engine management, schema initialization, and small DB helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import StaticPool

from salespulse.config import SCHEMA_PATH
from salespulse.exceptions import DatabaseNotInitializedError

_REFERENCE_TABLES = {
    "app_metadata",
    "customers",
    "products",
    "orders",
    "order_items",
    "returns",
    "payments",
    "import_batches",
    "rejected_records",
}


def create_db_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """Create a SQLite engine with foreign keys enabled on every connection."""
    if str(db_path) == ":memory:":
        url = URL.create("sqlite+pysqlite", database=":memory:")
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = URL.create("sqlite+pysqlite", database=str(path))

    kwargs: dict[str, Any] = {"echo": echo}
    if str(db_path) == ":memory:":
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.close()

    return engine


def get_schema_sql(schema_path: str | Path = SCHEMA_PATH) -> str:
    path = Path(schema_path)
    if not path.exists():
        raise DatabaseNotInitializedError(f"Schema file not found: {path}")
    return path.read_text(encoding="utf-8")


def initialize_database(
    engine: Engine | str | Path,
    *,
    schema_path: str | Path = SCHEMA_PATH,
) -> Engine:
    """Create all SalesPulse tables, views, indexes, and triggers.

    The operation is idempotent. Views are dropped and recreated so schema
    changes to analytical definitions are picked up by a repeat initialization.
    """
    if isinstance(engine, (str, Path)):
        engine = create_db_engine(engine)

    schema = get_schema_sql(schema_path)
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.executescript(schema)
        raw.commit()
        cursor.close()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return engine


def is_initialized(engine: Engine) -> bool:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    return _REFERENCE_TABLES.issubset(existing)


def require_initialized(engine: Engine) -> None:
    if not is_initialized(engine):
        raise DatabaseNotInitializedError(
            "SalesPulse database is not initialized. Run: python -m salespulse.cli init-db"
        )


def get_schema_version(engine: Engine) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM app_metadata WHERE key = 'schema_version'")
        ).fetchone()
    return None if row is None else str(row[0])


@contextmanager
def read_connection(engine: Engine) -> Iterator[Any]:
    with engine.connect() as conn:
        yield conn


def read_dataframe(
    engine: Engine,
    sql: str,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def execute_script(engine: Engine, sql: str) -> None:
    raw = engine.raw_connection()
    try:
        raw.executescript(sql)
        raw.commit()
    finally:
        raw.close()


def table_counts(engine: Engine) -> dict[str, int]:
    """Return row counts for the core business and audit tables."""
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in (
            "customers",
            "products",
            "orders",
            "order_items",
            "returns",
            "payments",
            "import_batches",
            "rejected_records",
        ):
            counts[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
    return counts


def database_integrity(engine: Engine) -> dict[str, Any]:
    """Run SQLite quick_check and foreign_key_check."""
    with engine.connect() as conn:
        quick_check = str(conn.exec_driver_sql("PRAGMA quick_check").scalar_one())
        fk_rows = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    return {
        "quick_check": quick_check,
        "foreign_key_violations": len(fk_rows),
        "foreign_key_details": [tuple(row) for row in fk_rows],
    }
