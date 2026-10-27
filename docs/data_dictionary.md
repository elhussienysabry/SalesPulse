# Data dictionary

SalesPulse stores its demo data in a local SQLite database at
`data/processed/salespulse.db`. The schema is defined in
[`sql/schema.sql`](../sql/schema.sql) and versioned as **1.0.0** in
`app_metadata`.

> **Synthetic data:** every customer, product, order, payment, and return is fictional. The demo
> uses seed `42` and data version `1.0.0`. Nothing in this repository describes a real person or
> business.

## Conventions

| Convention | Detail |
|---|---|
| Currency | USD, stored as SQLite `REAL`; displayed to two decimals |
| Dates | ISO-8601 `TEXT`, `YYYY-MM-DD`; validated in Python and with `CHECK` constraints |
| Import timestamps | UTC ISO-8601 with a `Z` suffix, for example `2026-10-27T19:07:06Z` |
| Row timestamps | `created_at` defaults to SQLite `datetime('now')` (UTC) |
| Booleans | Integer `0`/`1`; CSV accepts `true/false`, `yes/no`, `y/n`, `active/inactive` |
| Money rounding | Half-up to cents with a `+1e-9` epsilon in Python and SQL |
| Discounts | Decimal fraction, not percent: `0.15` means 15% |
| Foreign keys | Enabled on every SQLAlchemy connection with `PRAGMA foreign_keys = ON` |
| Dates in reports | Inclusive on both `date_from` and `date_to` |

## Entity relationships

```text
customers 1 ──── * orders 1 ──── * order_items * ──── 1 products
                     │                  │
                     │ 1                │ 1
                     ▼ *                ▼ *
                 payments            returns

import_batches 1 ──── * rejected_records
```

- One customer can place many orders.
- One order has one or more order items; `(order_id, product_id)` is unique.
- One order has at most one payment (`payments.order_id` is unique).
- One order item can have multiple return requests over time.
- Returns are only accepted for completed orders; the original order date is the reporting date.
- Every rejected source row is tied to exactly one import batch.

## Dimension tables

### `customers`

One row per fictional customer.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `customer_id` | `TEXT` | no | PK; `CUST-[0-9][0-9][0-9][0-9]` | Stable customer key |
| `first_name` | `TEXT` | no | non-blank after trim | Customer first name |
| `last_name` | `TEXT` | no | non-blank after trim | Customer last name |
| `email` | `TEXT` | no | unique; must contain `@` | Lower-cased, validated email address |
| `signup_date` | `TEXT` | no | valid ISO date | Date the customer account was created |
| `region` | `TEXT` | no | five-region allow-list | Customer profile region |
| `country` | `TEXT` | no | non-blank after trim | Customer profile country |
| `city` | `TEXT` | no | non-blank after trim | Customer profile city |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

`region` is one of `North America`, `Europe`, `Asia-Pacific`, `Latin America`,
`Middle East & Africa`.

### `products`

One row per fictional product.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `product_id` | `TEXT` | no | PK; `PROD-[0-9][0-9][0-9]` | Stable product key |
| `product_name` | `TEXT` | no | non-blank after trim | Display name |
| `category` | `TEXT` | no | six-category allow-list | Product category |
| `unit_price` | `REAL` | no | `> 0` and `<= 100000` | List price per unit |
| `unit_cost` | `REAL` | no | `>= 0` and `<= unit_price` | Cost per unit; stored but not used for margin reporting |
| `launch_date` | `TEXT` | no | valid ISO date | Product launch date |
| `is_active` | `INTEGER` | no | `0`/`1`, default `1` | Whether the product is currently sold |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

`category` is one of `Electronics`, `Home & Kitchen`, `Office`, `Sports & Outdoor`,
`Beauty`, `Accessories`.

## Transaction tables

### `orders`

One row per order header.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `order_id` | `TEXT` | no | PK; `ORD-[0-9][0-9][0-9][0-9][0-9]` | Stable order key |
| `customer_id` | `TEXT` | no | FK → `customers`; restrict update/delete | Customer who placed the order |
| `order_date` | `TEXT` | no | valid ISO date | Reporting date for the order |
| `status` | `TEXT` | no | `completed`, `pending`, `cancelled` | Current order state |
| `shipping_region` | `TEXT` | no | five-region allow-list | Region used for geographic reporting |
| `shipping_country` | `TEXT` | no | non-blank after trim | Shipping country |
| `shipping_city` | `TEXT` | no | non-blank after trim | Shipping city |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

Business rules enforced during ingestion:

- `customer_id` and `order_date` are immutable once the order exists.
- A status change is allowed only from `pending` to `completed` or `cancelled`.
- An order date cannot precede the customer's `signup_date`.
- Shipping attributes may be corrected on an existing order.

### `order_items`

One row per product line on an order.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `order_item_id` | `TEXT` | no | PK; `OI-[0-9][0-9][0-9][0-9][0-9][0-9][0-9]` | Stable line key |
| `order_id` | `TEXT` | no | FK → `orders`; restrict update/delete | Parent order |
| `product_id` | `TEXT` | no | FK → `products`; restrict update/delete | Product sold |
| `quantity` | `INTEGER` | no | `1..1000` | Units purchased on the line |
| `unit_price` | `REAL` | no | `0.01..100000` | Selling price per unit at order time |
| `discount_rate` | `REAL` | no | `0..0.90`; default `0` | Line discount as a fraction |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

Additional rules:

- `(order_id, product_id)` is unique, so a product appears at most once per order.
- `order_id` and `product_id` are immutable for an existing line.
- Existing line quantities, prices, and discounts may only change while the parent order is
  `pending`. New lines require the parent order and product to exist.

### `returns`

One row per return request or decision against an order line. A line can have several return rows
over time, subject to cumulative caps.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `return_id` | `TEXT` | no | PK; `RET-[0-9][0-9][0-9][0-9][0-9]` | Stable return key |
| `order_item_id` | `TEXT` | no | FK → `order_items`; restrict update/delete | Line being returned |
| `return_date` | `TEXT` | no | valid ISO date | Date the return was recorded |
| `quantity` | `INTEGER` | no | `1..1000` | Units returned on this request |
| `refund_amount` | `REAL` | no | `0..100000` | Refund for this request; must be `0` unless `approved` |
| `reason` | `TEXT` | no | six-reason allow-list | Why the customer returned the item |
| `status` | `TEXT` | no | `approved`, `requested`, `rejected` | Return decision |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

`reason` is one of `damaged`, `wrong_item`, `not_as_described`, `changed_mind`,
`late_delivery`, `other`.

Only `approved` returns affect revenue. Return quantity cannot exceed the purchased quantity, and
cumulative approved refunds cannot exceed the line's discounted value. Ingestion enforces these
rules and SQLite triggers enforce them again for direct SQL writes.

### `payments`

At most one payment row per order.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `payment_id` | `TEXT` | no | PK; `PAY-ORD-[0-9][0-9][0-9][0-9][0-9]` | Stable payment key |
| `order_id` | `TEXT` | no | unique FK → `orders`; restrict update/delete | Order being paid |
| `method` | `TEXT` | no | four-method allow-list | Payment method |
| `amount` | `REAL` | no | `0..10000000` | Amount captured or scheduled |
| `status` | `TEXT` | no | `paid`, `pending`, `failed` | Payment state |
| `paid_at` | `TEXT` | yes | valid ISO date or `NULL` | Required when `status = 'paid'`, otherwise `NULL` |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

`method` is one of `card`, `paypal`, `bank_transfer`, `cash_on_delivery`.

Additional rules:

- Payment amount must match the order's net sales within `$0.01`.
- Cancelled orders cannot have a payment.
- Completed orders require a `paid` payment.
- Pending orders may have a `pending` or `paid` payment.
- `paid_at` cannot precede the order date.

> **Note:** the demo's clean source has payments for 620 of the 680 orders. Pending and cancelled
> orders can legitimately have no payment row.

## Audit tables

### `import_batches`

One row per committed or failed ingestion attempt. A dry run executes the same transaction and
rolls it back, so dry runs do **not** leave a batch row.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `import_id` | `TEXT` | no | PK | `IMP-YYYYMMDDHHMMSS-XXXXXX` identifier |
| `dataset` | `TEXT` | no | one of the six source datasets | Dataset being loaded |
| `source_file` | `TEXT` | no | — | Original file name |
| `file_sha256` | `TEXT` | no | — | SHA-256 of the uploaded file |
| `started_at` | `TEXT` | no | — | UTC start timestamp |
| `completed_at` | `TEXT` | yes | — | UTC completion timestamp |
| `status` | `TEXT` | no | `processing`, `success`, `partial`, `failed` | Batch outcome |
| `total_rows` | `INTEGER` | no | `>= 0`; default `0` | Data rows read from the file |
| `inserted_rows` | `INTEGER` | no | `>= 0`; default `0` | New business rows written |
| `updated_rows` | `INTEGER` | no | `>= 0`; default `0` | Existing rows changed |
| `unchanged_rows` | `INTEGER` | no | `>= 0`; default `0` | Rows already present with identical values |
| `rejected_rows` | `INTEGER` | no | `>= 0`; default `0` | Rows stored in `rejected_records` |
| `error_message` | `TEXT` | yes | — | Failure reason for `failed` batches |

Status semantics:

| Status | Meaning |
|---|---|
| `processing` | Transaction is in progress; a crash can leave this state, and the quality checks flag stale rows |
| `success` | Every source row was accepted (inserted, updated, or unchanged) |
| `partial` | Some rows were rejected; all valid rows were committed and every rejection was recorded |
| `failed` | File/schema/execution failure; the whole batch was rolled back and the error is recorded |

A dry run returns a summary with normal counters but sets `dry_run = true`; the import is rolled
back and no audit rows remain.

### `rejected_records`

One row per rejected source row.

| Column | Type | Null | Constraint / default | Description |
|---|---|---|---|---|
| `rejection_id` | `INTEGER` | no | PK, autoincrement | Surrogate key |
| `import_id` | `TEXT` | no | FK → `import_batches`; cascade delete | Owning batch |
| `dataset` | `TEXT` | no | — | Dataset of the rejected row |
| `row_number` | `INTEGER` | no | `> 0` | CSV row number, counting the header as row 1 |
| `raw_data` | `TEXT` | no | JSON object | Original row values as read from the CSV |
| `reasons` | `TEXT` | no | `; `-separated | Human-readable rejection reasons (maximum 8 per row) |
| `created_at` | `TEXT` | no | `datetime('now')` | Database insertion timestamp |

Rejected rows never enter the business tables. Correct the source and re-import the file.

## Analytical views

The views are the single source of truth for financial measures. The dashboard, reports, exports,
and quality checks all read from them.

### `v_order_financials`

One row per order, including orders with no items.

| Column | Type | Description |
|---|---|---|
| `order_id` | `TEXT` | Order key |
| `customer_id` | `TEXT` | Customer key |
| `order_date` | `TEXT` | Reporting date |
| `status` | `TEXT` | Order status |
| `shipping_region` | `TEXT` | Shipping region |
| `shipping_country` | `TEXT` | Shipping country |
| `shipping_city` | `TEXT` | Shipping city |
| `item_count` | `INTEGER` | Number of order lines (`0` if none) |
| `unit_count` | `INTEGER` | Sum of line quantities |
| `gross_sales` | `REAL` | Sum of rounded line gross values, before discounts |
| `discount_amount` | `REAL` | Sum of rounded line discounts |
| `net_sales` | `REAL` | `gross_sales - discount_amount` |
| `refunds` | `REAL` | Approved refunds attached to the order, regardless of status |
| `returned_units` | `INTEGER` | Approved returned units attached to the order |
| `recognized_gross_sales` | `REAL` | `gross_sales` when completed, else `0` |
| `recognized_discount_amount` | `REAL` | `discount_amount` when completed, else `0` |
| `recognized_net_sales` | `REAL` | `net_sales` when completed, else `0` |
| `net_revenue` | `REAL` | `net_sales - refunds` when completed, else `0` |
| `is_revenue_recognized` | `INTEGER` | `1` when completed, else `0` |

The view does not filter by date; queries apply `order_date BETWEEN :date_from AND :date_to`.

### `v_order_line_financials`

One row per order item, joined to its order and product.

| Column | Type | Description |
|---|---|---|
| `order_item_id` | `TEXT` | Order-item key |
| `order_id` | `TEXT` | Parent order key |
| `product_id` | `TEXT` | Product key |
| `quantity` | `INTEGER` | Units on the line |
| `unit_price` | `REAL` | Selling price per unit |
| `discount_rate` | `REAL` | Discount fraction |
| `order_date` | `TEXT` | Reporting date |
| `status` | `TEXT` | Order status |
| `customer_id` | `TEXT` | Customer key |
| `shipping_region` | `TEXT` | Shipping region |
| `product_name` | `TEXT` | Product display name |
| `category` | `TEXT` | Product category |
| `unit_cost` | `REAL` | Product cost per unit |
| `gross_sales` | `REAL` | Rounded line gross value |
| `discount_amount` | `REAL` | Rounded line discount |
| `net_sales` | `REAL` | `gross_sales - discount_amount` |
| `returned_units` | `INTEGER` | Approved returned units on the line |
| `refunds` | `REAL` | Approved refunds on the line |
| `recognized_gross_sales` | `REAL` | `gross_sales` when completed, else `0` |
| `recognized_discount_amount` | `REAL` | `discount_amount` when completed, else `0` |
| `net_revenue` | `REAL` | `net_sales - refunds` when completed, else `0` |

## Indexes, triggers, and integrity

Indexes support the common access paths:

- `orders(order_date, status)` and `orders(customer_id)`
- `order_items(order_id)` and `order_items(product_id)`
- `returns(order_item_id, status)` and `returns(return_date)`
- `payments(order_id)`
- `import_batches(started_at)`
- `rejected_records(import_id)`

Triggers are a second line of defence against direct SQL writes:

| Trigger | Fires on | Rule |
|---|---|---|
| `trg_returns_quantity_insert` | insert into `returns` | Cumulative return quantity on a line cannot exceed the purchased quantity |
| `trg_returns_quantity_update` | update of quantity or item | Same rule, excluding the row being updated |
| `trg_returns_refund_insert` | insert into `returns` | Cumulative approved refunds cannot exceed the line's discounted value (`0.005` tolerance) |
| `trg_returns_refund_update` | update of refund, status, or item | Same rule, excluding the row being updated |

The ingestion layer reports violations as row rejections; the triggers protect the database if rows
are written outside the pipeline.

## CSV contracts

Six CSVs are supported. Files must be UTF-8 (a UTF-8 BOM is accepted), non-empty, no larger than
25 MB, parseable, and contain exactly the expected columns in any order. Column names are
case-sensitive. Extra columns are a schema error, not a warning.

| Dataset | Columns, in canonical order |
|---|---|
| `customers` | `customer_id`, `first_name`, `last_name`, `email`, `signup_date`, `region`, `country`, `city` |
| `products` | `product_id`, `product_name`, `category`, `unit_price`, `unit_cost`, `launch_date`, `is_active` |
| `orders` | `order_id`, `customer_id`, `order_date`, `status`, `shipping_region`, `shipping_country`, `shipping_city` |
| `order_items` | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_price`, `discount_rate` |
| `returns` | `return_id`, `order_item_id`, `return_date`, `quantity`, `refund_amount`, `reason`, `status` |
| `payments` | `payment_id`, `order_id`, `method`, `amount`, `status`, `paid_at` |

### CSV value contracts

| Field | Contract |
|---|---|
| IDs | Must match the documented prefix and digit count; leading zeros are significant |
| Dates | Exactly `YYYY-MM-DD`; must be a real calendar date, not in the future, and not before 2000-01-01 |
| `email` | One `@`, no whitespace, domain suffix of at least two letters; normalized to lower case |
| `region`, shipping region | Five canonical regions; documented aliases accepted when normalization is enabled |
| `category` | Six canonical categories; documented aliases accepted |
| `order.status` | `completed`, `pending`, `cancelled`; aliases such as `complete` and `canceled` accepted |
| `return.status` | `approved`, `requested`, `rejected`; aliases accepted |
| `return.reason` | Six canonical reasons; aliases accepted |
| `payment.method` | Four canonical methods; aliases accepted |
| `payment.status` | `paid`, `pending`, `failed`; aliases accepted |
| `quantity` | Whole number from 1 to 1,000 |
| `unit_price`, `amount`, `refund_amount` | At most two decimal places; non-negative where applicable |
| `discount_rate` | Fraction from `0` to `0.90`, at most two decimal places |
| `is_active` | `1/0`, `true/false`, `yes/no`, `y/n`, `active/inactive` |
| `paid_at` | Empty for `pending`/`failed`; required for `paid`; cannot precede the order date |

Empty strings are treated as missing, never as zero or a default. A missing required value is
rejected.

### Ingestion order

Rows are loaded in dependency order:

```text
customers → products → orders → order_items → returns → payments
```

Loading a child dataset before its parents produces unknown-key rejections; the batch is still
audited.

### Demo row counts

| Dataset | Clean rows | Messy rows | Messy rejections | Notes |
|---|---:|---:|---:|---|
| `customers` | 200 | 205 | 4 | One additional row uses an accepted region alias |
| `products` | 42 | 48 | 6 | Duplicate, missing name, bad price/category/cost, bad boolean |
| `orders` | 680 | 689 | 9 | Duplicate, unknown/missing customer, bad/future/pre-signup date, invalid status/region, missing city |
| `order_items` | 1,318 | 1,327 | 9 | Duplicate IDs/pairs, unknown keys, missing IDs, invalid quantity/price/discount |
| `returns` | 73 | 82 | 9 | Duplicate, unknown item, invalid quantity/refund/status/date, missing reason, caps |
| `payments` | 620 | 626 | 6 | Duplicate payment/order, unknown order, invalid method, negative amount, missing paid date |
| **Total** | **2,933** | **2,977** | **43** | Messy files contain all clean rows plus injected problems |

After the full demo, business tables hold the clean counts plus the one accepted messy customer, for
**201 customers**; the other 43 messy rows are stored in `rejected_records`.

## Metadata and reproducibility

- `app_metadata.schema_version` is `1.0.0`.
- The generator persists a manifest with seed, data version, date range, row counts, and SHA-256
  hashes for every CSV under `data/raw/clean/` and `data/raw/messy/`.
- Clean and messy files are regenerated byte-for-byte from seed `42` and data version `1.0.0`.
- Database files, raw CSVs, and exports are gitignored; only code, SQL, documentation, and
  screenshots are committed.
