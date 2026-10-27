"""Deterministic synthetic e-commerce data.

Everything in this module is fictional and reproducible from a seed. The same
seed, data version, and generator produce byte-identical CSV files.

Two datasets are produced:
* clean/  -- passes every validation and quality rule; used for the demo.
* messy/  -- a copy of clean plus documented bad and inconsistent rows; used to
             demonstrate rejection reports and label normalization.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from salespulse.config import DEFAULT_DATA_VERSION, DEFAULT_SEED
from salespulse.schema import EXPECTED_COLUMNS, INGESTION_ORDER
from salespulse.transformations import (
    PAYMENT_METHODS,
    REGIONS,
    RETURN_REASONS,
    round_money,
)

DATASET_FILENAMES = {
    "customers": "customers.csv",
    "products": "products.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "returns": "returns.csv",
    "payments": "payments.csv",
}

DATA_START = date(2025, 1, 1)
DATA_END = date(2026, 6, 30)
SIGNUP_START = date(2024, 1, 1)
SIGNUP_END = date(2026, 5, 31)

FIRST_NAMES = (
    "Avery",
    "Jordan",
    "Riley",
    "Morgan",
    "Casey",
    "Cameron",
    "Taylor",
    "Quinn",
    "Parker",
    "Reese",
    "Skyler",
    "Drew",
    "Elliot",
    "Emerson",
    "Finley",
    "Hayden",
    "Jesse",
    "Kendall",
    "Logan",
    "Marlow",
    "Noel",
    "Oakley",
    "Peyton",
    "Rowan",
    "Sage",
    "Shawn",
    "Tatum",
    "Blake",
    "Dakota",
    "Harper",
    "Iris",
    "Jamie",
    "Kai",
    "Lane",
    "Micah",
    "Nico",
    "Paris",
    "Remy",
    "Sasha",
    "Toby",
)
LAST_NAMES = (
    "Bennett",
    "Carter",
    "Diaz",
    "Ellis",
    "Foster",
    "Grant",
    "Hayes",
    "Ingram",
    "Jensen",
    "Keller",
    "Lawson",
    "Mercer",
    "Nolan",
    "Owens",
    "Porter",
    "Quinn",
    "Reed",
    "Sullivan",
    "Turner",
    "Underwood",
    "Vega",
    "Walker",
    "Young",
    "Zimmer",
    "Brooks",
    "Chen",
    "Das",
    "Evans",
    "Fischer",
    "Garcia",
    "Hughes",
    "Ibrahim",
)

LOCATIONS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "North America": (
        ("United States", ("Austin", "Seattle", "Chicago", "New York", "Denver")),
        ("Canada", ("Toronto", "Vancouver", "Montreal")),
    ),
    "Europe": (
        ("Germany", ("Berlin", "Munich", "Hamburg")),
        ("France", ("Paris", "Lyon")),
        ("United Kingdom", ("London", "Manchester")),
        ("Spain", ("Madrid", "Barcelona")),
    ),
    "Asia-Pacific": (
        ("Japan", ("Tokyo", "Osaka")),
        ("Australia", ("Sydney", "Melbourne")),
        ("India", ("Mumbai", "Bengaluru")),
        ("Singapore", ("Singapore",)),
    ),
    "Latin America": (
        ("Brazil", ("Sao Paulo", "Rio de Janeiro")),
        ("Mexico", ("Mexico City", "Guadalajara")),
    ),
    "Middle East & Africa": (
        ("United Arab Emirates", ("Dubai", "Abu Dhabi")),
        ("South Africa", ("Cape Town", "Johannesburg")),
        ("Egypt", ("Cairo", "Alexandria")),
    ),
}

PRODUCT_TEMPLATES: tuple[tuple[str, str, float, float], ...] = (
    ("Wireless Headphones", "Electronics", 89.99, 38.00),
    ("Bluetooth Speaker", "Electronics", 59.99, 24.50),
    ("USB-C Hub", "Electronics", 42.50, 16.00),
    ("Smart Watch", "Electronics", 149.00, 68.00),
    ("Noise-Cancelling Earbuds", "Electronics", 119.00, 51.00),
    ("Portable Charger", "Electronics", 34.99, 12.25),
    ("Mechanical Keyboard", "Electronics", 99.00, 44.00),
    ("Webcam", "Electronics", 74.50, 31.00),
    ("Ceramic Mug Set", "Home & Kitchen", 28.00, 9.50),
    ("Pour-Over Coffee Maker", "Home & Kitchen", 49.00, 18.00),
    ("Chef Knife", "Home & Kitchen", 65.00, 23.00),
    ("Bamboo Cutting Board", "Home & Kitchen", 32.50, 11.00),
    ("Linen Throw Blanket", "Home & Kitchen", 54.00, 21.50),
    ("Cast Iron Skillet", "Home & Kitchen", 44.00, 16.00),
    ("Glass Food Storage Set", "Home & Kitchen", 39.99, 14.00),
    ("Desk Organizer", "Office", 24.00, 7.50),
    ("Ergonomic Mouse", "Office", 39.99, 15.00),
    ("Laptop Stand", "Office", 47.50, 17.00),
    ("Franklin Planner", "Office", 31.00, 9.00),
    ("Desk Lamp", "Office", 58.00, 22.00),
    ("Sticky Note Bundle", "Office", 12.50, 3.00),
    ("Adjustable Dumbbell", "Sports & Outdoor", 129.00, 57.00),
    ("Yoga Mat", "Sports & Outdoor", 45.00, 14.50),
    ("Trail Backpack", "Sports & Outdoor", 89.00, 35.00),
    ("Insulated Water Bottle", "Sports & Outdoor", 27.00, 8.00),
    ("Resistance Band Kit", "Sports & Outdoor", 22.50, 6.00),
    ("Camping Lantern", "Sports & Outdoor", 36.00, 13.00),
    ("Vitamin C Serum", "Beauty", 34.00, 9.00),
    ("Hydrating Face Mask", "Beauty", 19.00, 5.00),
    ("Hair Repair Oil", "Beauty", 26.50, 8.00),
    ("Mineral Sunscreen", "Beauty", 28.00, 10.00),
    ("Bath Salt Set", "Beauty", 21.00, 6.00),
    ("Leather Card Holder", "Accessories", 29.00, 8.00),
    ("Canvas Tote", "Accessories", 24.00, 7.00),
    ("Travel Organizer", "Accessories", 35.50, 12.00),
    ("Minimalist Belt", "Accessories", 42.00, 15.00),
    ("Beanie", "Accessories", 18.00, 5.50),
    ("Sunglasses", "Accessories", 79.00, 28.00),
    ("Laptop Sleeve", "Accessories", 38.00, 13.00),
    ("Passport Holder", "Accessories", 26.00, 8.00),
)


@dataclass(frozen=True, slots=True)
class GeneratedData:
    """A complete, internally consistent set of source tables."""

    datasets: dict[str, pd.DataFrame]
    manifest: dict[str, object]

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.datasets[name]

    @property
    def counts(self) -> dict[str, int]:
        return {name: len(df) for name, df in self.datasets.items()}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _fmt_money(value: float) -> float:
    return round_money(value)


def _date_text(value: date) -> str:
    return value.isoformat()


def _iter_months(start: date, end: date) -> list[date]:
    months: list[date] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year, 12, 31)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


def _allocate_orders(order_count: int, months: list[date]) -> list[int]:
    """Allocate an exact order count across months with seasonality."""
    weights: list[float] = []
    n = max(len(months) - 1, 1)
    for i, month in enumerate(months):
        season = 0.45 if month.month in (11, 12) else 0.0
        summer = 0.12 if month.month in (6, 7) else 0.0
        weights.append(0.85 + 0.30 * (i / n) + season + summer)
    total_weight = sum(weights)
    raw = [order_count * w / total_weight for w in weights]
    counts = [max(1, int(value)) for value in raw]
    while sum(counts) > order_count:
        index = max(range(len(counts)), key=lambda idx: counts[idx])
        if counts[index] <= 1:
            break
        counts[index] -= 1
    remaining = order_count - sum(counts)
    ranked = sorted(range(len(raw)), key=lambda idx: raw[idx] - int(raw[idx]), reverse=True)
    for offset in range(remaining):
        counts[ranked[offset % len(ranked)]] += 1
    return counts


def generate_clean_data(
    *,
    seed: int = DEFAULT_SEED,
    data_version: str = DEFAULT_DATA_VERSION,
    customer_count: int = 200,
    product_count: int = 42,
    order_count: int | None = None,
    start_date: date = DATA_START,
    end_date: date = DATA_END,
) -> GeneratedData:
    """Generate a coherent set of clean source DataFrames."""
    if customer_count < 5:
        raise ValueError("customer_count must be at least 5")
    if product_count < 6:
        raise ValueError("product_count must be at least 6")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if order_count is None:
        order_count = max(20, round(customer_count * 3.4))
    if order_count < 1:
        raise ValueError("order_count must be positive")

    rng = random.Random(seed)
    months = [m for m in _iter_months(start_date, end_date) if m <= end_date]
    if not months:
        raise ValueError("date range must include at least one month")

    # --- Customers ---------------------------------------------------------
    customers: list[dict[str, object]] = []
    for index in range(customer_count):
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index * 7 + 3) % len(LAST_NAMES)]
        region = rng.choice(REGIONS)
        country, cities = rng.choice(LOCATIONS[region])
        city = rng.choice(cities)
        signup_span = (SIGNUP_END - SIGNUP_START).days
        signup = SIGNUP_START + timedelta(days=int((rng.random() ** 0.85) * signup_span))
        customers.append(
            {
                "customer_id": f"CUST-{index + 1:04d}",
                "first_name": first,
                "last_name": last,
                "email": f"{_slug(first)}.{_slug(last)}.{index + 1:03d}@example.test",
                "signup_date": _date_text(signup),
                "region": region,
                "country": country,
                "city": city,
            }
        )
    customers_df = pd.DataFrame(customers, columns=EXPECTED_COLUMNS["customers"])

    # --- Products ----------------------------------------------------------
    products: list[dict[str, object]] = []
    for index in range(product_count):
        template_name, category, base_price, base_cost = PRODUCT_TEMPLATES[
            index % len(PRODUCT_TEMPLATES)
        ]
        edition = index // len(PRODUCT_TEMPLATES)
        suffix = "" if edition == 0 else f" {edition + 1}"
        price = _fmt_money(base_price * rng.uniform(0.96, 1.08))
        cost = _fmt_money(min(price * 0.85, base_cost * rng.uniform(0.92, 1.08)))
        launch = date(2023, 1, 1) + timedelta(days=rng.randint(0, 900))
        if launch > SIGNUP_END:
            launch = SIGNUP_END
        products.append(
            {
                "product_id": f"PROD-{index + 1:03d}",
                "product_name": f"{template_name}{suffix}",
                "category": category,
                "unit_price": price,
                "unit_cost": cost,
                "launch_date": _date_text(launch),
                "is_active": 1 if rng.random() > 0.05 else 0,
            }
        )
    products_df = pd.DataFrame(products, columns=EXPECTED_COLUMNS["products"])
    popularity = {
        row["product_id"]: rng.uniform(0.35, 2.4) if row["is_active"] else 0.08 for row in products
    }
    product_lookup = {
        row["product_id"]: {
            "price": float(row["unit_price"]),
            "category": row["category"],
        }
        for row in products
    }
    customer_lookup = {row["customer_id"]: row for row in customers}
    customer_ids = list(customer_lookup)
    eligible_by_date: dict[str, list[str]] = {}

    def eligible_customers(on_date: date) -> list[str]:
        key = on_date.isoformat()
        if key not in eligible_by_date:
            eligible_by_date[key] = [
                cid
                for cid in customer_ids
                if date.fromisoformat(str(customer_lookup[cid]["signup_date"])) <= on_date
            ]
        return eligible_by_date[key]

    # --- Orders ------------------------------------------------------------
    month_counts = _allocate_orders(order_count, months)
    order_dates: list[date] = []
    for month, count in zip(months, month_counts, strict=True):
        last_day = min(_month_end(month), end_date)
        first_day = max(month, start_date)
        span = (last_day - first_day).days
        for _ in range(count):
            order_dates.append(first_day + timedelta(days=rng.randint(0, max(span, 0))))
    order_dates.sort()

    orders: list[dict[str, object]] = []
    for index, order_date in enumerate(order_dates, start=1):
        pool = eligible_customers(order_date)
        if not pool:
            pool = customer_ids
        if rng.random() < 0.27:
            newish = [
                cid
                for cid in pool
                if 0
                <= (order_date - date.fromisoformat(str(customer_lookup[cid]["signup_date"]))).days
                <= 75
            ]
            customer_id = rng.choice(newish or pool)
        else:
            customer_id = rng.choice(pool)
        customer = customer_lookup[customer_id]
        if rng.random() < 0.78:
            region = str(customer["region"])
            country = str(customer["country"])
            city = str(customer["city"])
        else:
            region = rng.choice(REGIONS)
            country, cities = rng.choice(LOCATIONS[region])
            city = rng.choice(cities)
        status_roll = rng.random()
        if status_roll < 0.86:
            status = "completed"
        elif status_roll < 0.92:
            status = "pending"
        else:
            status = "cancelled"
        orders.append(
            {
                "order_id": f"ORD-{index:05d}",
                "customer_id": customer_id,
                "order_date": _date_text(order_date),
                "status": status,
                "shipping_region": region,
                "shipping_country": country,
                "shipping_city": city,
            }
        )
    orders_df = pd.DataFrame(orders, columns=EXPECTED_COLUMNS["orders"])

    # --- Order items -------------------------------------------------------
    order_items: list[dict[str, object]] = []
    item_number = 0
    product_ids = [row["product_id"] for row in products]
    weights = [popularity[pid] for pid in product_ids]
    discount_values = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    discount_weights = [44, 17, 14, 10, 7, 5, 3]
    for order in orders:
        item_count = rng.choices([1, 2, 3, 4], weights=[38, 36, 19, 7], k=1)[0]
        chosen: list[str] = []
        while len(chosen) < item_count:
            candidate = rng.choices(product_ids, weights=weights, k=1)[0]
            if candidate not in chosen:
                chosen.append(candidate)
        for product_id in chosen:
            item_number += 1
            quantity = rng.choices([1, 2, 3, 4, 5], weights=[38, 31, 17, 10, 4], k=1)[0]
            discount = rng.choices(discount_values, weights=discount_weights, k=1)[0]
            order_items.append(
                {
                    "order_item_id": f"OI-{item_number:07d}",
                    "order_id": order["order_id"],
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": product_lookup[product_id]["price"],
                    "discount_rate": discount,
                }
            )
    order_items_df = pd.DataFrame(order_items, columns=EXPECTED_COLUMNS["order_items"])

    # --- Returns -----------------------------------------------------------
    completed_order_ids = set(orders_df.loc[orders_df["status"] == "completed", "order_id"])
    order_dates_by_id = dict(zip(orders_df["order_id"], orders_df["order_date"], strict=True))
    eligible_returns = order_items_df[order_items_df["order_id"].isin(completed_order_ids)]
    return_count = 0
    if len(eligible_returns) >= 10:
        return_count = max(1, round(len(eligible_returns) * 0.065))
    elif len(eligible_returns) > 0:
        return_count = 1
    return_rows: list[dict[str, object]] = []
    if return_count:
        sampled_positions = sorted(
            rng.sample(range(len(eligible_returns)), k=min(return_count, len(eligible_returns)))
        )
        for position, (_, item) in enumerate(eligible_returns.iloc[sampled_positions].iterrows()):
            quantity = rng.randint(1, int(item["quantity"]))
            roll = rng.random()
            if position == 0 or roll < 0.82:
                return_status = "approved"
            elif roll < 0.92:
                return_status = "requested"
            else:
                return_status = "rejected"
            order_date = date.fromisoformat(str(order_dates_by_id[item["order_id"]]))
            return_date = order_date + timedelta(days=rng.randint(3, 40))
            line_value = (
                float(item["quantity"])
                * float(item["unit_price"])
                * (1 - float(item["discount_rate"]))
            )
            refund = (
                _fmt_money(line_value * (quantity / float(item["quantity"])))
                if return_status == "approved"
                else 0.0
            )
            return_rows.append(
                {
                    "return_id": f"RET-{position + 1:05d}",
                    "order_item_id": item["order_item_id"],
                    "return_date": _date_text(return_date),
                    "quantity": quantity,
                    "refund_amount": refund,
                    "reason": rng.choice(RETURN_REASONS),
                    "status": return_status,
                }
            )
    returns_df = pd.DataFrame(return_rows, columns=EXPECTED_COLUMNS["returns"])

    # --- Payments ----------------------------------------------------------
    line_nets = pd.Series(
        [
            round_money(float(quantity) * float(unit_price) * (1 - float(discount_rate)))
            for quantity, unit_price, discount_rate in zip(
                order_items_df["quantity"],
                order_items_df["unit_price"],
                order_items_df["discount_rate"],
                strict=True,
            )
        ],
        index=order_items_df.index,
    )
    net_by_order = (
        order_items_df.assign(line_net=line_nets)
        .groupby("order_id", as_index=False)["line_net"]
        .sum()
        .assign(line_net=lambda frame: frame["line_net"].map(round_money))
    )
    payment_amounts = dict(zip(net_by_order["order_id"], net_by_order["line_net"], strict=True))
    payments: list[dict[str, object]] = []
    for order in orders:
        if order["status"] == "cancelled":
            continue
        order_id = str(order["order_id"])
        is_paid = order["status"] == "completed"
        payments.append(
            {
                "payment_id": f"PAY-ORD-{order_id.split('-')[1]}",
                "order_id": order_id,
                "method": rng.choice(PAYMENT_METHODS),
                "amount": _fmt_money(payment_amounts[order_id]),
                "status": "paid" if is_paid else "pending",
                "paid_at": order["order_date"] if is_paid else "",
            }
        )
    payments_df = pd.DataFrame(payments, columns=EXPECTED_COLUMNS["payments"])

    datasets = {
        "customers": customers_df,
        "products": products_df,
        "orders": orders_df,
        "order_items": order_items_df,
        "returns": returns_df,
        "payments": payments_df,
    }
    manifest = {
        "project": "SalesPulse",
        "dataset": "clean",
        "synthetic": True,
        "seed": seed,
        "data_version": data_version,
        "generated_with": "salespulse.synthetic_data.generate_clean_data",
        "date_range": {"from": start_date.isoformat(), "to": end_date.isoformat()},
        "row_counts": {name: len(df) for name, df in datasets.items()},
        "notes": "All names, customers, products, and transactions are fictional.",
    }
    return GeneratedData(datasets=datasets, manifest=manifest)


# ---------------------------------------------------------------------------
# Messy dataset construction
# ---------------------------------------------------------------------------


def _append(frame: pd.DataFrame, **values: object) -> None:
    row = {column: values.get(column, "") for column in frame.columns}
    frame.loc[len(frame)] = row


def _mutate(frame: pd.DataFrame, position: int, **values: object) -> None:
    for column, value in values.items():
        frame.at[position, column] = value


def build_messy_data(clean: GeneratedData, *, seed: int = DEFAULT_SEED) -> GeneratedData:
    """Create a documented dirty dataset from the clean baseline.

    The mutations target specific, reproducible rows. Duplicates are appended
    after the originals, so the first occurrence remains the one a human would
    expect to be accepted.
    """
    rng = random.Random(seed + 10_000)
    data = {name: clean[name].copy() for name in INGESTION_ORDER}

    # Customers -------------------------------------------------------------
    customers = data["customers"]
    first_customer = customers.iloc[0].to_dict()
    current_region = str(customers.at[0, "region"])
    region_alias = {
        "North America": "north america",
        "Europe": "europe",
        "Asia-Pacific": "asia pacific",
        "Latin America": "latam",
        "Middle East & Africa": "middle east and africa",
    }[current_region]
    _mutate(customers, 0, region=region_alias)  # normalizable alias of same value
    _append(customers, **first_customer)  # duplicate customer_id
    _append(
        customers,
        customer_id="CUST-9001",
        first_name="Missing",
        last_name="Email",
        email="",
        signup_date="2025-03-01",
        region="Europe",
        country="Germany",
        city="Berlin",
    )
    _append(
        customers,
        customer_id="CUST-9002",
        first_name="Bad",
        last_name="Date",
        email="bad.date@example.test",
        signup_date="2026-02-30",
        region="Europe",
        country="France",
        city="Paris",
    )
    _append(
        customers,
        customer_id="CUST-9003",
        first_name="Bad",
        last_name="Email",
        email="not-an-email",
        signup_date="2025-04-01",
        region="Asia-Pacific",
        country="Japan",
        city="Tokyo",
    )
    _append(
        customers,
        customer_id="CUST-9004",
        first_name="Normalized",
        last_name="Alias",
        email="normalized.alias@example.test",
        signup_date="2025-05-01",
        region="europe",
        country="Spain",
        city="Madrid",
    )

    # Products --------------------------------------------------------------
    products = data["products"]
    first_product = products.iloc[0].to_dict()
    aliased_category = "Home & Kitchen"
    if not (products["category"] == aliased_category).any():
        aliased_category = str(products["category"].iloc[0])
    aliased_position = int(products.index[products["category"] == aliased_category][0])
    category_aliases = {
        "Electronics": "electronic",
        "Home & Kitchen": "home and kitchen",
        "Office": "office supplies",
        "Sports & Outdoor": "sports and outdoor",
        "Beauty": "personal care",
        "Accessories": "accessory",
    }
    _mutate(
        products,
        aliased_position,
        category=category_aliases[aliased_category],
    )  # normalizable alias
    _append(products, **first_product)  # duplicate product_id
    _append(
        products,
        product_id="PROD-901",
        product_name="",
        category="Office",
        unit_price="19.99",
        unit_cost="5.00",
        launch_date="2025-01-01",
        is_active="1",
    )
    _append(
        products,
        product_id="PROD-902",
        product_name="Negative Price",
        category="Beauty",
        unit_price="-5.00",
        unit_cost="1.00",
        launch_date="2025-01-01",
        is_active="1",
    )
    _append(
        products,
        product_id="PROD-903",
        product_name="Unknown Category",
        category="Garden",
        unit_price="22.00",
        unit_cost="7.00",
        launch_date="2025-01-01",
        is_active="1",
    )
    _append(
        products,
        product_id="PROD-904",
        product_name="Bad Cost",
        category="Office",
        unit_price="20.00",
        unit_cost="25.00",
        launch_date="2025-01-01",
        is_active="1",
    )
    _append(
        products,
        product_id="PROD-905",
        product_name="Bad Active Flag",
        category="Office",
        unit_price="20.00",
        unit_cost="8.00",
        launch_date="2025-01-01",
        is_active="maybe",
    )

    # Orders ----------------------------------------------------------------
    orders = data["orders"]
    first_order = orders.iloc[0].to_dict()
    completed_rows = orders.index[orders["status"] == "completed"]
    completed_pos = int(completed_rows[0]) if len(completed_rows) else int(orders.index[0])
    _mutate(orders, completed_pos, status="Complete")  # normalizable alias
    first_customer_id = str(customers.iloc[0]["customer_id"])
    _append(orders, **first_order)  # duplicate order_id
    _append(
        orders,
        order_id="ORD-90001",
        customer_id="CUST-9999",
        order_date="2025-04-01",
        status="completed",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90002",
        customer_id="",
        order_date="2025-04-02",
        status="completed",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90003",
        customer_id=first_customer_id,
        order_date="2026-02-30",
        status="pending",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90004",
        customer_id=first_customer_id,
        order_date="2099-01-15",
        status="pending",
        shipping_region="North America",
        shipping_country="United States",
        shipping_city="Austin",
    )
    _append(
        orders,
        order_id="ORD-90005",
        customer_id=first_customer_id,
        order_date="2020-01-01",
        status="completed",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90006",
        customer_id=first_customer_id,
        order_date="2025-06-01",
        status="shipped",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90007",
        customer_id=first_customer_id,
        order_date="2025-06-02",
        status="completed",
        shipping_region="Mars",
        shipping_country="France",
        shipping_city="Paris",
    )
    _append(
        orders,
        order_id="ORD-90008",
        customer_id=first_customer_id,
        order_date="2025-06-03",
        status="completed",
        shipping_region="Europe",
        shipping_country="France",
        shipping_city="",
    )
    # Order items -----------------------------------------------------------
    items = data["order_items"]
    first_item = items.iloc[0].to_dict()
    _append(items, **first_item)  # duplicate item ID
    _append(
        items,
        order_item_id="OI-9000001",
        order_id=first_item["order_id"],
        product_id=first_item["product_id"],
        quantity=1,
        unit_price=first_item["unit_price"],
        discount_rate=0,
    )  # duplicate order/product business key
    _append(
        items,
        order_item_id="OI-9000002",
        order_id="ORD-99999",
        product_id=first_item["product_id"],
        quantity=1,
        unit_price="10.00",
        discount_rate="0",
    )
    _append(
        items,
        order_item_id="OI-9000003",
        order_id=first_item["order_id"],
        product_id="PROD-999",
        quantity=1,
        unit_price="10.00",
        discount_rate="0",
    )
    _append(
        items,
        order_item_id="OI-9000004",
        order_id=first_item["order_id"],
        product_id=first_item["product_id"],
        quantity=0,
        unit_price="10.00",
        discount_rate="0",
    )
    _append(
        items,
        order_item_id="OI-9000005",
        order_id=first_item["order_id"],
        product_id=first_item["product_id"],
        quantity=1,
        unit_price="-10.00",
        discount_rate="0",
    )
    _append(
        items,
        order_item_id="OI-9000006",
        order_id=first_item["order_id"],
        product_id=first_item["product_id"],
        quantity=1,
        unit_price="10.00",
        discount_rate="1.50",
    )
    _append(
        items,
        order_item_id="OI-123",
        order_id=first_item["order_id"],
        product_id=first_item["product_id"],
        quantity=1,
        unit_price="10.00",
        discount_rate="0",
    )
    _append(
        items,
        order_item_id="OI-9000007",
        order_id="",
        product_id=first_item["product_id"],
        quantity=1,
        unit_price="10.00",
        discount_rate="0",
    )

    # Returns ---------------------------------------------------------------
    returns = data["returns"]
    if not returns.empty:
        first_return = returns.iloc[0].to_dict()
        approved_position = int(returns.index[returns["status"] == "approved"][0])
        _mutate(returns, approved_position, status="Approved")  # normalizable alias
        _append(returns, **first_return)  # duplicate return_id
        _append(
            returns,
            return_id="RET-90001",
            order_item_id="OI-9999999",
            return_date="2025-06-10",
            quantity=1,
            refund_amount="10.00",
            reason="damaged",
            status="approved",
        )
        _append(
            returns,
            return_id="RET-90002",
            order_item_id=first_return["order_item_id"],
            return_date="2025-06-10",
            quantity="9999",
            refund_amount="10.00",
            reason="damaged",
            status="approved",
        )
        _append(
            returns,
            return_id="RET-90003",
            order_item_id=first_return["order_item_id"],
            return_date="2026-02-30",
            quantity=1,
            refund_amount="5.00",
            reason="damaged",
            status="approved",
        )
        _append(
            returns,
            return_id="RET-90004",
            order_item_id=first_return["order_item_id"],
            return_date="2025-06-10",
            quantity=1,
            refund_amount="-5.00",
            reason="damaged",
            status="approved",
        )
        _append(
            returns,
            return_id="RET-90005",
            order_item_id=first_return["order_item_id"],
            return_date="2025-06-10",
            quantity=1,
            refund_amount="5.00",
            reason="changed_mind",
            status="maybe",
        )
        _append(
            returns,
            return_id="RET-90006",
            order_item_id=first_return["order_item_id"],
            return_date="2025-06-10",
            quantity=1,
            refund_amount="999999.00",
            reason="damaged",
            status="approved",
        )
        _append(
            returns,
            return_id="RET-90007",
            order_item_id=first_return["order_item_id"],
            return_date="2020-01-01",
            quantity=1,
            refund_amount="0.00",
            reason="other",
            status="requested",
        )
        _append(
            returns,
            return_id="RET-90008",
            order_item_id=first_return["order_item_id"],
            return_date="2025-06-10",
            quantity=1,
            refund_amount="0.00",
            reason="",
            status="requested",
        )

    # Payments --------------------------------------------------------------
    payments = data["payments"]
    first_payment = payments.iloc[0].to_dict()
    _append(payments, **first_payment)  # duplicate payment_id / order_id
    _append(
        payments,
        payment_id="PAY-ORD-90001",
        order_id="ORD-99999",
        method="card",
        amount="10.00",
        status="paid",
        paid_at="2025-06-01",
    )
    _append(
        payments,
        payment_id="PAY-ORD-90002",
        order_id=first_payment["order_id"],
        method="crypto",
        amount="10.00",
        status="paid",
        paid_at="2025-06-01",
    )
    _append(
        payments,
        payment_id="PAY-ORD-90003",
        order_id=first_payment["order_id"],
        method="card",
        amount="-10.00",
        status="paid",
        paid_at="2025-06-01",
    )
    _append(
        payments,
        payment_id="PAY-ORD-90004",
        order_id=first_payment["order_id"],
        method="card",
        amount="999.00",
        status="paid",
        paid_at="2025-06-01",
    )  # amount mismatch
    _append(
        payments,
        payment_id="PAY-ORD-90005",
        order_id=first_payment["order_id"],
        method="card",
        amount="10.00",
        status="paid",
        paid_at="",
    )  # paid without a date
    # Ensure generated missing values do not accidentally become NaN labels.
    for frame in data.values():
        frame.reset_index(drop=True, inplace=True)

    manifest = {
        **clean.manifest,
        "dataset": "messy",
        "row_counts": {name: len(df) for name, df in data.items()},
        "notes": (
            "Deliberately dirty dataset. It contains duplicate IDs, missing required values, "
            "invalid dates, invalid quantities/prices, unknown foreign keys, invalid statuses, "
            "and normalizable categorical aliases. All content is fictional."
        ),
        "injected_issue_counts": {
            "customers": 4,
            "products": 6,
            "orders": 9,
            "order_items": 9,
            "returns": 9,
            "payments": 6,
        },
        "random_marker": rng.randint(1, 1_000_000),
    }
    return GeneratedData(datasets=data, manifest=manifest)


def write_datasets(
    generated: GeneratedData,
    directory: str | Path,
    *,
    dataset_label: str | None = None,
) -> dict[str, object]:
    """Write CSVs plus a manifest and return a manifest enriched with hashes."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in INGESTION_ORDER:
        frame = generated.datasets[name]
        path = target / DATASET_FILENAMES[name]
        frame.to_csv(path, index=False, lineterminator="\n", float_format="%.2f")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = dict(generated.manifest)
    if dataset_label:
        manifest["dataset"] = dataset_label
    manifest["files"] = {
        name: {
            "filename": DATASET_FILENAMES[name],
            "sha256": hashes[name],
            "row_count": len(generated.datasets[name]),
        }
        for name in INGESTION_ORDER
    }
    manifest["columns"] = {name: list(generated.datasets[name].columns) for name in INGESTION_ORDER}
    (target / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def write_all_datasets(
    directory: str | Path,
    *,
    seed: int = DEFAULT_SEED,
    data_version: str = DEFAULT_DATA_VERSION,
    customer_count: int = 200,
    product_count: int = 42,
    order_count: int | None = None,
) -> dict[str, object]:
    """Generate and write clean/ and messy/ under the supplied raw directory."""
    raw_dir = Path(directory)
    clean = generate_clean_data(
        seed=seed,
        data_version=data_version,
        customer_count=customer_count,
        product_count=product_count,
        order_count=order_count,
    )
    messy = build_messy_data(clean, seed=seed)
    clean_manifest = write_datasets(clean, raw_dir / "clean", dataset_label="clean")
    messy_manifest = write_datasets(messy, raw_dir / "messy", dataset_label="messy")
    return {
        "clean": clean_manifest,
        "messy": messy_manifest,
        "clean_dir": str(raw_dir / "clean"),
        "messy_dir": str(raw_dir / "messy"),
    }


def expected_messy_rejections(dataset: str) -> int:
    """Documented count of rows that must be rejected in the messy baseline.

    This is intentionally a small, human-readable contract used in tests and
    documentation. It is derived from the injected issues above.
    """
    return {
        "customers": 4,
        "products": 6,
        "orders": 9,
        "order_items": 9,
        "returns": 9,
        "payments": 6,
    }[dataset]


def dataset_status_counts(generated: GeneratedData) -> dict[str, Counter[str]]:
    """Small summary helper used in docs and tests."""
    return {
        name: Counter(generated[name]["status"].astype(str))
        for name in ("orders", "returns", "payments")
    }
