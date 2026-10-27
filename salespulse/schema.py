"""Schema metadata used by validation, testing, and documentation helpers."""

from __future__ import annotations

from salespulse.config import SCHEMA_PATH

CORE_TABLES = (
    "customers",
    "products",
    "orders",
    "order_items",
    "returns",
    "payments",
    "import_batches",
    "rejected_records",
)

ANALYTICAL_VIEWS = ("v_order_financials", "v_order_line_financials")

DATASET_TABLES = {
    "customers": "customers",
    "products": "products",
    "orders": "orders",
    "order_items": "order_items",
    "returns": "returns",
    "payments": "payments",
}

INGESTION_ORDER = ("customers", "products", "orders", "order_items", "returns", "payments")

EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": (
        "customer_id",
        "first_name",
        "last_name",
        "email",
        "signup_date",
        "region",
        "country",
        "city",
    ),
    "products": (
        "product_id",
        "product_name",
        "category",
        "unit_price",
        "unit_cost",
        "launch_date",
        "is_active",
    ),
    "orders": (
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "shipping_region",
        "shipping_country",
        "shipping_city",
    ),
    "order_items": (
        "order_item_id",
        "order_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount_rate",
    ),
    "returns": (
        "return_id",
        "order_item_id",
        "return_date",
        "quantity",
        "refund_amount",
        "reason",
        "status",
    ),
    "payments": (
        "payment_id",
        "order_id",
        "method",
        "amount",
        "status",
        "paid_at",
    ),
}

DATASET_KEY: dict[str, str] = {
    "customers": "customer_id",
    "products": "product_id",
    "orders": "order_id",
    "order_items": "order_item_id",
    "returns": "return_id",
    "payments": "payment_id",
}

PRIMARY_KEY_COLUMNS = DATASET_KEY

SCHEMA_FILE = SCHEMA_PATH
