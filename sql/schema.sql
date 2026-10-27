-- SalesPulse SQLite schema
-- ---------------------------------------------------------------------------
-- All monetary values are stored in USD as REAL to two decimal places.
-- Dates are ISO-8601 TEXT values (YYYY-MM-DD), validated by both the pipeline
-- and CHECK constraints. Timestamps are UTC ISO-8601 TEXT values.
--
-- Revenue recognition rules are centralised in the v_order_financials and
-- v_order_line_financials views documented in docs/metric_definitions.md.
-- ---------------------------------------------------------------------------

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

INSERT OR IGNORE INTO app_metadata (key, value) VALUES ('schema_version', '1.0.0');

-- ---------------------------------------------------------------------------
-- Dimension tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS customers (
    customer_id  TEXT PRIMARY KEY
                 CHECK (customer_id GLOB 'CUST-[0-9][0-9][0-9][0-9]'),
    first_name   TEXT NOT NULL CHECK (length(trim(first_name)) > 0),
    last_name    TEXT NOT NULL CHECK (length(trim(last_name)) > 0),
    email        TEXT NOT NULL UNIQUE CHECK (instr(email, '@') > 1),
    signup_date  TEXT NOT NULL
                 CHECK (signup_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                        AND date(signup_date) = signup_date),
    region       TEXT NOT NULL
                 CHECK (region IN ('North America', 'Europe', 'Asia-Pacific',
                                   'Latin America', 'Middle East & Africa')),
    country      TEXT NOT NULL CHECK (length(trim(country)) > 0),
    city         TEXT NOT NULL CHECK (length(trim(city)) > 0),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    product_id    TEXT PRIMARY KEY
                  CHECK (product_id GLOB 'PROD-[0-9][0-9][0-9]'),
    product_name  TEXT NOT NULL CHECK (length(trim(product_name)) > 0),
    category      TEXT NOT NULL
                  CHECK (category IN ('Electronics', 'Home & Kitchen', 'Office',
                                      'Sports & Outdoor', 'Beauty', 'Accessories')),
    unit_price    REAL NOT NULL CHECK (unit_price > 0 AND unit_price <= 100000),
    unit_cost     REAL NOT NULL CHECK (unit_cost >= 0 AND unit_cost <= unit_price),
    launch_date   TEXT NOT NULL
                  CHECK (launch_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                         AND date(launch_date) = launch_date),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Transaction tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY
                     CHECK (order_id GLOB 'ORD-[0-9][0-9][0-9][0-9][0-9]'),
    customer_id      TEXT NOT NULL REFERENCES customers(customer_id) ON UPDATE RESTRICT
                     ON DELETE RESTRICT,
    order_date       TEXT NOT NULL
                     CHECK (order_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                            AND date(order_date) = order_date),
    status           TEXT NOT NULL
                     CHECK (status IN ('completed', 'pending', 'cancelled')),
    shipping_region  TEXT NOT NULL
                     CHECK (shipping_region IN ('North America', 'Europe', 'Asia-Pacific',
                                                'Latin America', 'Middle East & Africa')),
    shipping_country TEXT NOT NULL CHECK (length(trim(shipping_country)) > 0),
    shipping_city    TEXT NOT NULL CHECK (length(trim(shipping_city)) > 0),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id  TEXT PRIMARY KEY
                   CHECK (order_item_id GLOB 'OI-[0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    order_id       TEXT NOT NULL REFERENCES orders(order_id) ON UPDATE RESTRICT
                   ON DELETE RESTRICT,
    product_id     TEXT NOT NULL REFERENCES products(product_id) ON UPDATE RESTRICT
                   ON DELETE RESTRICT,
    quantity       INTEGER NOT NULL CHECK (quantity > 0 AND quantity <= 1000),
    unit_price     REAL NOT NULL CHECK (unit_price > 0 AND unit_price <= 100000),
    discount_rate  REAL NOT NULL DEFAULT 0
                   CHECK (discount_rate >= 0 AND discount_rate <= 0.90),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (order_id, product_id)
);

CREATE TABLE IF NOT EXISTS returns (
    return_id      TEXT PRIMARY KEY
                   CHECK (return_id GLOB 'RET-[0-9][0-9][0-9][0-9][0-9]'),
    order_item_id  TEXT NOT NULL REFERENCES order_items(order_item_id) ON UPDATE RESTRICT
                   ON DELETE RESTRICT,
    return_date    TEXT NOT NULL
                   CHECK (return_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                          AND date(return_date) = return_date),
    quantity       INTEGER NOT NULL CHECK (quantity > 0 AND quantity <= 1000),
    refund_amount  REAL NOT NULL CHECK (refund_amount >= 0 AND refund_amount <= 100000),
    reason         TEXT NOT NULL
                   CHECK (reason IN ('damaged', 'wrong_item', 'not_as_described',
                                     'changed_mind', 'late_delivery', 'other')),
    status         TEXT NOT NULL
                   CHECK (status IN ('approved', 'requested', 'rejected')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id  TEXT PRIMARY KEY
                CHECK (payment_id GLOB 'PAY-ORD-[0-9][0-9][0-9][0-9][0-9]'),
    order_id    TEXT NOT NULL UNIQUE REFERENCES orders(order_id) ON UPDATE RESTRICT
                ON DELETE RESTRICT,
    method      TEXT NOT NULL
                CHECK (method IN ('card', 'paypal', 'bank_transfer', 'cash_on_delivery')),
    amount      REAL NOT NULL CHECK (amount >= 0 AND amount <= 10000000),
    status      TEXT NOT NULL CHECK (status IN ('paid', 'pending', 'failed')),
    paid_at     TEXT
                CHECK (paid_at IS NULL
                       OR (paid_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                           AND date(paid_at) = paid_at)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ((status = 'paid' AND paid_at IS NOT NULL)
           OR (status IN ('pending', 'failed') AND paid_at IS NULL))
);

-- ---------------------------------------------------------------------------
-- Import audit tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS import_batches (
    import_id       TEXT PRIMARY KEY,
    dataset         TEXT NOT NULL
                    CHECK (dataset IN ('customers', 'products', 'orders', 'order_items',
                                       'returns', 'payments')),
    source_file     TEXT NOT NULL,
    file_sha256     TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL
                    CHECK (status IN ('processing', 'success', 'partial', 'failed')),
    total_rows      INTEGER NOT NULL DEFAULT 0 CHECK (total_rows >= 0),
    inserted_rows   INTEGER NOT NULL DEFAULT 0 CHECK (inserted_rows >= 0),
    updated_rows    INTEGER NOT NULL DEFAULT 0 CHECK (updated_rows >= 0),
    unchanged_rows  INTEGER NOT NULL DEFAULT 0 CHECK (unchanged_rows >= 0),
    rejected_rows   INTEGER NOT NULL DEFAULT 0 CHECK (rejected_rows >= 0),
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS rejected_records (
    rejection_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id     TEXT NOT NULL REFERENCES import_batches(import_id) ON DELETE CASCADE,
    dataset       TEXT NOT NULL,
    row_number    INTEGER NOT NULL CHECK (row_number > 0),
    raw_data      TEXT NOT NULL,
    reasons       TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Indexes for common analytical and operational access paths
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_orders_date_status ON orders(order_date, status);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_returns_item_status ON returns(order_item_id, status);
CREATE INDEX IF NOT EXISTS idx_returns_date ON returns(return_date);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_started ON import_batches(started_at);
CREATE INDEX IF NOT EXISTS idx_rejected_records_import ON rejected_records(import_id);

-- ---------------------------------------------------------------------------
-- Integrity triggers for returns. Ingestion reports these as rejected rows;
-- the triggers are a second line of defence against direct SQL writes.
-- ---------------------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_returns_quantity_insert
BEFORE INSERT ON returns
WHEN NEW.quantity + COALESCE(
        (SELECT SUM(r.quantity) FROM returns r WHERE r.order_item_id = NEW.order_item_id), 0
     ) > COALESCE(
        (SELECT oi.quantity FROM order_items oi WHERE oi.order_item_id = NEW.order_item_id), 0
     )
BEGIN
    SELECT RAISE(ABORT, 'return quantity exceeds purchased quantity');
END;

CREATE TRIGGER IF NOT EXISTS trg_returns_quantity_update
BEFORE UPDATE OF quantity, order_item_id ON returns
WHEN NEW.quantity + COALESCE(
        (SELECT SUM(r.quantity) FROM returns r
         WHERE r.order_item_id = NEW.order_item_id AND r.return_id <> OLD.return_id), 0
     ) > COALESCE(
        (SELECT oi.quantity FROM order_items oi WHERE oi.order_item_id = NEW.order_item_id), 0
     )
BEGIN
    SELECT RAISE(ABORT, 'return quantity exceeds purchased quantity');
END;

CREATE TRIGGER IF NOT EXISTS trg_returns_refund_insert
BEFORE INSERT ON returns
WHEN NEW.status = 'approved'
     AND NEW.refund_amount + COALESCE(
        (SELECT SUM(r.refund_amount) FROM returns r
         WHERE r.order_item_id = NEW.order_item_id AND r.status = 'approved'), 0
     ) > COALESCE(
        (SELECT ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_rate) + 1e-9, 2)
         FROM order_items oi WHERE oi.order_item_id = NEW.order_item_id), 0
     ) + 0.005
BEGIN
    SELECT RAISE(ABORT, 'approved refunds exceed line net sales');
END;

CREATE TRIGGER IF NOT EXISTS trg_returns_refund_update
BEFORE UPDATE OF refund_amount, status, order_item_id ON returns
WHEN NEW.status = 'approved'
     AND NEW.refund_amount + COALESCE(
        (SELECT SUM(r.refund_amount) FROM returns r
         WHERE r.order_item_id = NEW.order_item_id AND r.status = 'approved'
           AND r.return_id <> OLD.return_id), 0
     ) > COALESCE(
        (SELECT ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_rate) + 1e-9, 2)
         FROM order_items oi WHERE oi.order_item_id = NEW.order_item_id), 0
     ) + 0.005
BEGIN
    SELECT RAISE(ABORT, 'approved refunds exceed line net sales');
END;

-- ---------------------------------------------------------------------------
-- Analytical views: the single source of truth for financial measures
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS v_order_financials;
CREATE VIEW v_order_financials AS
WITH item_totals AS (
    SELECT
        order_id,
        COUNT(*) AS item_count,
        SUM(quantity) AS unit_count,
        ROUND(SUM(ROUND(quantity * unit_price + 1e-9, 2)), 2) AS gross_sales,
        ROUND(SUM(ROUND(quantity * unit_price * discount_rate + 1e-9, 2)), 2) AS discount_amount,
        ROUND(SUM(ROUND(quantity * unit_price * (1 - discount_rate) + 1e-9, 2)), 2) AS net_sales
    FROM order_items
    GROUP BY order_id
),
approved_refunds AS (
    SELECT
        oi.order_id,
        SUM(r.quantity) AS returned_units,
        ROUND(SUM(r.refund_amount), 2) AS refunds
    FROM returns r
    JOIN order_items oi ON oi.order_item_id = r.order_item_id
    WHERE r.status = 'approved'
    GROUP BY oi.order_id
)
SELECT
    o.order_id,
    o.customer_id,
    o.order_date,
    o.status,
    o.shipping_region,
    o.shipping_country,
    o.shipping_city,
    COALESCE(it.item_count, 0) AS item_count,
    COALESCE(it.unit_count, 0) AS unit_count,
    COALESCE(it.gross_sales, 0.0) AS gross_sales,
    COALESCE(it.discount_amount, 0.0) AS discount_amount,
    COALESCE(it.net_sales, 0.0) AS net_sales,
    COALESCE(ar.refunds, 0.0) AS refunds,
    COALESCE(ar.returned_units, 0) AS returned_units,
    CASE WHEN o.status = 'completed'
         THEN COALESCE(it.gross_sales, 0.0) ELSE 0.0 END AS recognized_gross_sales,
    CASE WHEN o.status = 'completed'
         THEN COALESCE(it.discount_amount, 0.0) ELSE 0.0 END AS recognized_discount_amount,
    CASE WHEN o.status = 'completed'
         THEN COALESCE(it.net_sales, 0.0) ELSE 0.0 END AS recognized_net_sales,
    CASE WHEN o.status = 'completed'
         THEN COALESCE(it.net_sales, 0.0) - COALESCE(ar.refunds, 0.0)
         ELSE 0.0 END AS net_revenue,
    CASE WHEN o.status = 'completed' THEN 1 ELSE 0 END AS is_revenue_recognized
FROM orders o
LEFT JOIN item_totals it ON it.order_id = o.order_id
LEFT JOIN approved_refunds ar ON ar.order_id = o.order_id;

DROP VIEW IF EXISTS v_order_line_financials;
CREATE VIEW v_order_line_financials AS
WITH approved_line_returns AS (
    SELECT
        order_item_id,
        SUM(quantity) AS returned_units,
        ROUND(SUM(refund_amount), 2) AS refunds
    FROM returns
    WHERE status = 'approved'
    GROUP BY order_item_id
)
SELECT
    oi.order_item_id,
    oi.order_id,
    oi.product_id,
    oi.quantity,
    oi.unit_price,
    oi.discount_rate,
    o.order_date,
    o.status,
    o.customer_id,
    o.shipping_region,
    p.product_name,
    p.category,
    p.unit_cost,
    ROUND(oi.quantity * oi.unit_price + 1e-9, 2) AS gross_sales,
    ROUND(oi.quantity * oi.unit_price * oi.discount_rate + 1e-9, 2) AS discount_amount,
    ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_rate) + 1e-9, 2) AS net_sales,
    COALESCE(alr.returned_units, 0) AS returned_units,
    COALESCE(alr.refunds, 0.0) AS refunds,
    CASE WHEN o.status = 'completed'
         THEN ROUND(oi.quantity * oi.unit_price + 1e-9, 2) ELSE 0.0 END AS recognized_gross_sales,
    CASE WHEN o.status = 'completed'
         THEN ROUND(oi.quantity * oi.unit_price * oi.discount_rate + 1e-9, 2) ELSE 0.0 END
         AS recognized_discount_amount,
    CASE WHEN o.status = 'completed'
         THEN ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_rate) + 1e-9, 2)
              - COALESCE(alr.refunds, 0.0)
         ELSE 0.0 END AS net_revenue
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN approved_line_returns alr ON alr.order_item_id = oi.order_item_id;
