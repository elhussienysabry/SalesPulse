"""Contract tests for the deterministic synthetic data generator."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from salespulse.synthetic_data import (
    DATASET_FILENAMES,
    build_messy_data,
    expected_messy_rejections,
    generate_clean_data,
    write_all_datasets,
)
from salespulse.transformations import (
    CATEGORIES,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    REGIONS,
    RETURN_REASONS,
    RETURN_STATUSES,
    round_money,
)

DEFAULT_COUNTS = {
    "customers": 200,
    "products": 42,
    "orders": 680,
    "order_items": 1318,
    "returns": 73,
    "payments": 620,
}


@pytest.fixture(scope="module")
def clean():
    return generate_clean_data(seed=42)


def test_default_dataset_counts_are_stable(clean) -> None:
    assert clean.counts == DEFAULT_COUNTS


def test_generation_is_deterministic_for_same_seed() -> None:
    first = generate_clean_data(seed=42, customer_count=60, product_count=12, order_count=100)
    second = generate_clean_data(seed=42, customer_count=60, product_count=12, order_count=100)
    for name in DATASET_FILENAMES:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_clean_categories_and_statuses_are_canonical(clean) -> None:
    assert set(clean["customers"]["region"]) <= set(REGIONS)
    assert set(clean["products"]["category"]) <= set(CATEGORIES)
    assert set(clean["orders"]["status"]) <= set(ORDER_STATUSES)
    assert set(clean["returns"]["reason"]) <= set(RETURN_REASONS)
    assert set(clean["returns"]["status"]) <= set(RETURN_STATUSES)
    assert set(clean["payments"]["method"]) <= set(PAYMENT_METHODS)
    assert set(clean["payments"]["status"]) <= set(PAYMENT_STATUSES)


def test_clean_referential_integrity(clean) -> None:
    customers = set(clean["customers"]["customer_id"])
    products = set(clean["products"]["product_id"])
    orders = clean["orders"]
    items = clean["order_items"]
    returns = clean["returns"]
    payments = clean["payments"]

    assert set(orders["customer_id"]) <= customers
    assert set(items["order_id"]) <= set(orders["order_id"])
    assert set(items["product_id"]) <= products
    assert not items.duplicated(subset=["order_id", "product_id"]).any()
    assert set(returns["order_item_id"]) <= set(items["order_item_id"])
    assert set(payments["order_id"]) <= set(orders["order_id"])

    completed = set(orders.loc[orders["status"] == "completed", "order_id"])
    returned_orders = set(
        items.loc[items["order_item_id"].isin(returns["order_item_id"]), "order_id"]
    )
    assert returned_orders <= completed
    assert set(payments.loc[payments["status"] == "paid", "order_id"]) == completed


def test_clean_payment_amounts_and_refunds_reconcile(clean) -> None:
    items = clean["order_items"].copy()
    items["line_net"] = [
        round_money(float(qty) * float(price) * (1 - float(discount)))
        for qty, price, discount in zip(
            items["quantity"], items["unit_price"], items["discount_rate"], strict=True
        )
    ]
    expected = items.groupby("order_id")["line_net"].sum().map(round_money)
    payments = clean["payments"].set_index("order_id")["amount"]
    differences = (expected - payments).abs()
    assert differences.max() <= 0.01

    by_item = items.set_index("order_item_id")
    for row in clean["returns"].itertuples(index=False):
        item = by_item.loc[row.order_item_id]
        assert row.quantity <= int(item["quantity"])
        if row.status == "approved":
            assert row.refund_amount <= round_money(float(item["line_net"])) + 0.005


def test_returns_and_payment_dates_follow_order(clean) -> None:
    order_dates = clean["orders"].set_index("order_id")["order_date"]
    item_orders = clean["order_items"].set_index("order_item_id")["order_id"]
    for row in clean["returns"].itertuples(index=False):
        assert row.return_date >= order_dates.loc[item_orders.loc[row.order_item_id]]
    for row in clean["payments"].itertuples(index=False):
        if row.status == "paid":
            assert row.paid_at >= order_dates.loc[row.order_id]


def test_messy_dataset_contract() -> None:
    clean = generate_clean_data(seed=42, customer_count=60, product_count=12, order_count=100)
    messy = build_messy_data(clean, seed=42)
    assert messy.counts == {
        "customers": 65,
        "products": 18,
        "orders": 109,
        "order_items": 205,
        "returns": 20,
        "payments": 96,
    }
    for dataset, expected in {
        "customers": 4,
        "products": 6,
        "orders": 9,
        "order_items": 9,
        "returns": 9,
        "payments": 6,
    }.items():
        assert expected_messy_rejections(dataset) == expected
    assert messy.manifest["synthetic"] is True
    assert messy.manifest["dataset"] == "messy"
    assert "duplicate" in messy.manifest["notes"]
    assert messy.manifest["injected_issue_counts"] == {
        "customers": 4,
        "products": 6,
        "orders": 9,
        "order_items": 9,
        "returns": 9,
        "payments": 6,
    }


def test_written_files_and_manifest_hashes(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    manifest = write_all_datasets(
        raw,
        seed=42,
        customer_count=60,
        product_count=12,
        order_count=100,
    )
    for label in ("clean", "messy"):
        for dataset, filename in DATASET_FILENAMES.items():
            path = raw / label / filename
            assert path.exists() and path.stat().st_size > 0
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert manifest[label]["files"][dataset]["sha256"] == digest
        assert (raw / label / "_manifest.json").exists()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"customer_count": 4}, "at least 5"),
        ({"product_count": 5}, "at least 6"),
        ({"order_count": 0}, "positive"),
    ],
)
def test_generator_rejects_invalid_sizes(kwargs, match) -> None:
    with pytest.raises(ValueError, match=match):
        generate_clean_data(seed=1, **kwargs)
