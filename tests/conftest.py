"""Shared deterministic fixtures for the SalesPulse test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from salespulse.database import create_db_engine, initialize_database
from salespulse.ingestion import ingest_file
from salespulse.schema import INGESTION_ORDER
from salespulse.synthetic_data import DATASET_FILENAMES, write_all_datasets

TEST_SEED = 42
TEST_CUSTOMERS = 60
TEST_PRODUCTS = 12
TEST_ORDERS = 100


def _ingest_directory(engine: Engine, directory: Path) -> dict[str, object]:
    summaries = {}
    for dataset in INGESTION_ORDER:
        summaries[dataset] = ingest_file(
            engine,
            directory / DATASET_FILENAMES[dataset],
            dataset,
        )
    return summaries


@pytest.fixture(scope="session")
def raw_data(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    """Generate one small deterministic clean/messy dataset for the whole session."""
    root = tmp_path_factory.mktemp("raw")
    manifest = write_all_datasets(
        root,
        seed=TEST_SEED,
        customer_count=TEST_CUSTOMERS,
        product_count=TEST_PRODUCTS,
        order_count=TEST_ORDERS,
    )
    return root, manifest


@pytest.fixture(scope="session")
def clean_engine(tmp_path_factory: pytest.TempPathFactory, raw_data) -> Engine:
    root, _manifest = raw_data
    engine = create_db_engine(tmp_path_factory.mktemp("clean-db") / "salespulse.db")
    initialize_database(engine)
    summaries = _ingest_directory(engine, root / "clean")
    assert all(summary.rejected_rows == 0 for summary in summaries.values())
    return engine


@pytest.fixture(scope="session")
def messy_engine(
    tmp_path_factory: pytest.TempPathFactory, raw_data
) -> tuple[Engine, dict[str, object]]:
    root, _manifest = raw_data
    engine = create_db_engine(tmp_path_factory.mktemp("messy-db") / "salespulse.db")
    initialize_database(engine)
    _ingest_directory(engine, root / "clean")
    summaries = _ingest_directory(engine, root / "messy")
    return engine, summaries
