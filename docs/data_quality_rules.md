# Data-quality rules

SalesPulse is built around one principle: **reject, don't repair.** Only a small, documented set of
text normalizations is automatic. Everything else that fails the contract is stored in
`rejected_records` with a row number, the original values, and a reason, so a human can fix the
source and re-import it.

This document describes the file gates, row rules, cross-table business rules, database
safeguards, the messy demo dataset, and the 25 quality checks.

> All demo data is synthetic. The expected rejection counts in this document are part of the test
> contract and are asserted in `tests/`.

## Enforcement layers

| Layer | When it runs | What happens on failure |
|---|---|---|
| 1. File gate | Before parsing | The batch fails; a `failed` audit row is written (unless it is a dry run) |
| 2. Schema check | After parsing, before row validation | Missing or unexpected columns fail the batch |
| 3. Static row validation | Before the write transaction | Bad rows become rejections; valid rows continue |
| 4. Cross-table business rules | Inside the write transaction | Bad rows become rejections; the transaction still commits if other rows are valid |
| 5. Database constraints and triggers | During writes, including direct SQL | The write is rejected with a database error |
| 6. Post-load quality checks | After loading | Failures are reported for review; checks never mutate data |

A batch with zero rejections is `success`; a batch with one or more rejections is `partial`; an
unexpected exception rolls the whole batch back and records `failed`. Valid rows from a partial
batch are committed, and every rejected row is committed in the same transaction.

## Layer 1: file gates

| Rule | Detail |
|---|---|
| Exists | The path must exist and be a regular file |
| Non-empty | Zero-byte files fail |
| Size | Maximum **25 MB** (25 × 1024 × 1024 bytes) |
| Encoding | UTF-8; a UTF-8 BOM is accepted via `utf-8-sig` |
| Parseable | Must parse as CSV with a header |
| Data rows | At least one data row is required |
| Dashboard upload | The same 25 MB limit applies to browser uploads |

Dry runs follow the same gates. A file-level failure during a dry run is raised to the user and is
not written to the audit tables.

## Layer 2: schema rules

- Exactly the expected column names are required; names are case-sensitive.
- Columns may appear in any order; the pipeline selects the canonical order.
- Missing columns and unexpected columns are both errors, not warnings.
- The full per-dataset column list is in [data_dictionary.md](data_dictionary.md#csv-contracts).

## Normalization: the complete automatic set

These transformations are applied before validation. Nothing else is silently changed.

### Text and email

| Transformation | Example |
|---|---|
| Strip leading/trailing whitespace | `"  Avery  "` → `"Avery"` |
| Collapse internal whitespace | `"New   York"` → `"New York"` |
| Remove ASCII control characters | `"Avery\x00"` → `"Avery"` |
| Lower-case email | `"Avery.Ellis@Example.Test"` → `"avery.ellis@example.test"` |
| Trim numeric currency decoration | `"$1,234.50"` → `1234.50`; `"(12.00)"` → `-12.00` |

The numeric decoration support applies to parsed money fields. Negative values are still rejected
where the field requires a non-negative value.

### Categorical aliases

Aliases are matched after trimming, whitespace collapsing, and case-folding. Canonical values are
also accepted. Unknown values are rejected.

**Regions** — canonical: `North America`, `Europe`, `Asia-Pacific`, `Latin America`,
`Middle East & Africa`.

| Accepted aliases (case-insensitive) | Canonical |
|---|---|
| `north america`, `north-america`, `na` | North America |
| `europe`, `eu`, `emea` | Europe |
| `asia-pacific`, `asia pacific`, `apac`, `asia` | Asia-Pacific |
| `latin america`, `latam`, `south america` | Latin America |
| `middle east & africa`, `middle east and africa`, `mea`, `africa` | Middle East & Africa |

**Categories** — canonical: `Electronics`, `Home & Kitchen`, `Office`, `Sports & Outdoor`,
`Beauty`, `Accessories`.

| Accepted aliases | Canonical |
|---|---|
| `electronic` | Electronics |
| `home and kitchen`, `home kitchen`, `kitchen` | Home & Kitchen |
| `office supplies` | Office |
| `sports and outdoor`, `sports`, `outdoor` | Sports & Outdoor |
| `personal care` | Beauty |
| `accessory` | Accessories |

**Order status** — canonical: `completed`, `pending`, `cancelled`.

| Accepted aliases | Canonical |
|---|---|
| `complete`, `done`, `fulfilled` | completed |
| `processing` | pending |
| `canceled`, `void` | cancelled |

**Return status** — canonical: `approved`, `requested`, `rejected`.

| Accepted aliases | Canonical |
|---|---|
| `accepted` | approved |
| `pending` | requested |
| `denied` | rejected |

**Return reason** — canonical: `damaged`, `wrong_item`, `not_as_described`, `changed_mind`,
`late_delivery`, `other`.

| Accepted aliases | Canonical |
|---|---|
| `broken` | damaged |
| `wrong item` | wrong_item |
| `not as described` | not_as_described |
| `changed mind` | changed_mind |
| `late delivery` | late_delivery |

**Payment method** — canonical: `card`, `paypal`, `bank_transfer`, `cash_on_delivery`.

| Accepted aliases | Canonical |
|---|---|
| `credit card`, `credit_card`, `debit card` | card |
| `pay pal` | paypal |
| `bank transfer`, `banktransfer` | bank_transfer |
| `cash on delivery`, `cod` | cash_on_delivery |

**Payment status** — canonical: `paid`, `pending`, `failed`.

| Accepted aliases | Canonical |
|---|---|
| `settled`, `complete` | paid |
| `declined` | failed |

**Booleans** — canonical `1`/`0`.

| Accepted truthy values | Accepted falsy values |
|---|---|
| `1`, `true`, `yes`, `y`, `active` | `0`, `false`, `no`, `n`, `inactive` |

Normalization can be disabled for a single import with `--no-normalize-labels` (CLI) or the
dashboard checkbox. When disabled, only the canonical value itself is accepted; a documented alias
becomes a rejection.

## Layer 3: static row rules

### Universal rules

| Rule | Detail |
|---|---|
| Required values | Empty strings are missing; they are not converted to zero |
| ID formats | `CUST-####`, `PROD-###`, `ORD-#####`, `OI-#######`, `RET-#####`, `PAY-ORD-#####` |
| Dates | Exactly `YYYY-MM-DD`; real calendar date; not in the future; not before `2000-01-01` |
| Text length | Names, cities, and countries are limited to 120 characters after trimming |
| Money | At most two decimal places; parsed with decimal arithmetic |
| Integers | Whole numbers only (no `1.5`, no `1,000` unless the field accepts decoration) |
| In-file duplicates | Duplicate primary keys, duplicate customer emails, duplicate `(order_id, product_id)` pairs, and duplicate payment orders are rejected |
| Rejection detail | Maximum 8 reasons per row; each reason at most 500 characters; stored `reasons` text capped at 2,000 characters; raw JSON capped at 4,000 characters |

### Dataset-specific rules

| Dataset | Rules |
|---|---|
| `customers` | `first_name`, `last_name`, `email`, `signup_date`, `region`, `country`, `city` required; email format; email lower-cased; unique ID and email within the file |
| `products` | Name and category required; `unit_price` 0.01–100,000; `unit_cost` 0–100,000 and `<= unit_price`; launch date valid; `is_active` boolean; unique ID |
| `orders` | Customer, date, status, shipping region/country/city required; status and region allow-lists; unique ID |
| `order_items` | Order and product IDs required; quantity 1–1,000; unit price 0.01–100,000; discount 0–0.90; unique item ID and unique `(order_id, product_id)` within the file |
| `returns` | Item, date, quantity, refund, reason, status required; quantity 1–1,000; refund 0–100,000; status/reason allow-lists; unique ID |
| `payments` | Order, method, amount, status required; amount 0–10,000,000; method/status allow-lists; `paid_at` required for `paid` and empty otherwise; unique payment ID and at most one payment per order in the file |

## Layer 4: cross-table business rules

These checks run row by row inside the write transaction, after the referenced parents exist.

### Orders

- `customer_id` must exist in `customers`.
- `order_date` cannot be earlier than the customer's `signup_date`.
- `customer_id` and `order_date` are immutable for an existing order.
- Status may change only `pending → completed` or `pending → cancelled`.
- Shipping region, country, and city may be corrected on an existing order.

### Order items

- `order_id` must exist and `product_id` must exist.
- `(order_id, product_id)` must be unique in the database.
- `order_id` and `product_id` are immutable for an existing line.
- Existing quantity, unit price, or discount may change only while the parent order is `pending`.
- New lines are accepted when both parents exist.

### Returns

- The order item must exist.
- The parent order must be `completed`.
- `return_date` cannot precede the order date.
- Only `approved` returns may have a non-zero `refund_amount`; all others must be `0.00`.
- A single approved refund cannot exceed the net value of the returned quantity:
  `quantity × unit_price × (1 − discount_rate)`.
- Cumulative return quantity on a line cannot exceed the purchased quantity.
- Cumulative approved refunds on a line cannot exceed the line's discounted value.
- `order_item_id` is immutable for an existing return.

### Payments

- The order must exist.
- Cancelled orders cannot have a payment.
- `amount` must equal the order's net sales within `$0.01`.
- Completed orders require `status = 'paid'`.
- Pending orders accept `pending` or `paid`.
- `paid_at` cannot precede the order date.
- At most one payment is allowed per order, and `order_id` is immutable.

## Layer 5: database safeguards

The SQLite schema repeats the most important constraints:

- Primary keys, foreign keys, uniqueness, enum allow-lists, non-blank text checks, date `GLOB`
  checks, numeric range checks, and payment `paid_at` consistency.
- `order_items` unique `(order_id, product_id)`.
- `payments.order_id` unique.
- Four triggers covering cumulative return quantity and approved refunds, with a `$0.005`
  tolerance to accommodate floating-point cents.
- `PRAGMA foreign_keys = ON` on every engine connection.

The ingestion layer is expected to reject bad rows first; the database is the second line of
defence against direct writes.

## Layer 6: quality checks

There are **25 checks**: 21 SQL checks plus four database/runtime checks. Each returns a failure
count; zero is `pass`, anything else is `fail`.

### Critical checks (20)

| Check | What a failure means |
|---|---|
| `orphan_orders` | An order references a customer that does not exist |
| `orphan_order_items` | A line references a missing order or product |
| `orphan_returns` | A return references a missing order item |
| `orphan_payments` | A payment references a missing order |
| `duplicate_primary_keys` | Duplicate business keys exist in any core table |
| `duplicate_order_item_business_keys` | More than one line for the same `(order_id, product_id)` |
| `missing_required_values` | A required key/name/email field is blank |
| `invalid_statuses` | A status is outside the documented allow-list |
| `invalid_quantities_or_prices` | Quantity, price, discount, or refund is outside its range |
| `date_sequence_errors` | A return precedes its order, a payment precedes its order, or an order precedes signup |
| `returns_on_non_completed_orders` | A return is attached to a pending or cancelled order |
| `return_quantity_exceeds_purchase` | Cumulative returned units exceed the purchased quantity |
| `approved_refunds_exceed_line_net` | Cumulative approved refunds exceed the line's discounted value |
| `payments_for_cancelled_orders` | A cancelled order has a payment |
| `payment_amount_mismatch` | Payment differs from order net sales by more than `$0.01` |
| `completed_orders_without_items` | A completed order has no lines and cannot contribute revenue |
| `revenue_reconciliation_order_vs_line` | Order-level net revenue and line-level totals differ by more than `$0.01` |
| `revenue_component_reconciliation` | Completed net sales − approved refunds does not equal net revenue within `$0.01` |
| `database_quick_check` | `PRAGMA quick_check` returns anything other than `ok` |
| `foreign_key_integrity` | `PRAGMA foreign_key_check` reports violations |

### Warning checks (5)

| Check | What a failure means |
|---|---|
| `duplicate_order_events` | The same customer/date/item value appears more than once; could be legitimate repeats |
| `orders_future_dated` | An order date is after the current UTC date |
| `imports_with_failures` | A `failed` import batch exists; the detail also reports `processing` batches |
| `schema_version` | `app_metadata.schema_version` is missing |
| `stuck_import_batches` | A batch has been `processing` for more than one hour |

`duplicate_order_events` is intentionally a warning: a customer can legitimately place two orders
on the same day for the same amount. It prompts review rather than blocking reporting.

### Running the checks

```bash
python -m salespulse.cli quality
python -m salespulse.cli quality --export output/data_quality.csv
```

The dashboard **Data & Imports → Quality checks** tab shows severity, failures, status, detail,
recommended action, and database row counts. The Excel workbook includes a **Data Quality** sheet,
and CSV exports include `16_data_quality.csv`. Checks are read-only.

## Reconciliation definitions

| Check | Formula |
|---|---|
| Order vs line revenue | `ABS(SUM(v_order_financials.net_revenue) − SUM(v_order_line_financials.net_revenue)) <= 0.01` |
| Revenue components | `ABS(SUM(completed net_sales) − SUM(completed refunds) − SUM(completed net_revenue)) <= 0.01` |
| Payment amount | `ABS(payment.amount − order.net_sales) <= 0.01` for completed and pending orders |
| Return quantity | `SUM(return.quantity on line) <= order_item.quantity` |
| Refund cap | `SUM(approved refunds on line) <= ROUND(quantity × unit_price × (1 − discount_rate), 2) + 0.005` |

Financial values are rounded half-up to cents with a `+1e-9` epsilon in both Python and SQL. The
small tolerance in reconciliation checks prevents false failures from binary floating-point cents.

## Idempotency and re-import behavior

- The import batch stores the file's SHA-256, but idempotency is decided row by row, not by hash.
- A row with identical values is counted as `unchanged`.
- A row with changed mutable fields is counted as `updated`.
- A new row is counted as `inserted`.
- Re-importing the same file twice never duplicates business rows or rejection records from the
  first run.
- Rejections from the second import are recorded against the new batch, even if the reasons match.

## The messy demo dataset

`data/raw/messy/` contains every clean row plus 43 deliberately bad rows. The generator records
the intended issue counts in `_manifest.json`, and the tests assert the rejection totals.

| Dataset | Rows | Inserted | Unchanged | Rejected | Expected issue count |
|---|---:|---:|---:|---:|---:|
| customers | 205 | 1 | 200 | 4 | 4 (+1 accepted alias row) |
| products | 48 | 0 | 42 | 6 | 6 |
| orders | 689 | 0 | 680 | 9 | 9 |
| order_items | 1,327 | 0 | 1,318 | 9 | 9 |
| returns | 82 | 0 | 73 | 9 | 9 |
| payments | 626 | 0 | 620 | 6 | 6 |
| **Total** | **2,977** | **1** | **2,933** | **43** | **43** |

### What each rejected row demonstrates

**Customers**

| Row | Reason |
|---:|---|
| 202 | Duplicate `customer_id` and duplicate email |
| 203 | Missing email |
| 204 | Invalid calendar date (`2026-02-30`) |
| 205 | Invalid email format |

Row 201 is accepted because it uses a documented region alias; it is the one extra customer in the
final database (201 vs. 200 clean).

**Products**

| Row | Reason |
|---:|---|
| 44 | Duplicate `product_id` |
| 45 | Missing product name |
| 46 | Negative unit price |
| 47 | Unknown category (`Garden`) |
| 48 | Unit cost greater than unit price |
| 49 | Invalid active flag (`maybe`) |

**Orders**

| Row | Reason |
|---:|---|
| 682 | Duplicate `order_id` |
| 683 | Unknown customer |
| 684 | Missing customer |
| 685 | Invalid calendar date |
| 686 | Future order date |
| 687 | Order date before customer signup |
| 688 | Invalid status (`shipped`) |
| 689 | Invalid region (`Mars`) |
| 690 | Missing shipping city |

**Order items**

| Row | Reason |
|---:|---|
| 1320 | Duplicate item ID and duplicate order/product pair |
| 1321 | Duplicate order/product pair |
| 1322 | Unknown order |
| 1323 | Unknown product |
| 1324 | Quantity below 1 |
| 1325 | Negative unit price |
| 1326 | Discount above 0.90 |
| 1327 | Invalid item ID format |
| 1328 | Missing order ID |

**Returns**

| Row | Reason |
|---:|---|
| 75 | Duplicate `return_id` |
| 76 | Unknown order item |
| 77 | Quantity above 1,000 |
| 78 | Invalid calendar date |
| 79 | Negative refund |
| 80 | Invalid return status (`maybe`) |
| 81 | Refund above the 100,000 ceiling |
| 82 | Return date before the order date; cumulative quantity exceeds purchase |
| 83 | Missing reason |

**Payments**

| Row | Reason |
|---:|---|
| 622 | Duplicate payment ID and duplicate payment for the order |
| 623 | Unknown order |
| 624 | Invalid payment method (`crypto`) |
| 625 | Negative amount |
| 626 | Additional payment for an order that already has one (the intended amount mismatch is caught as a duplicate first) |
| 627 | Missing `paid_at` for a paid payment; also duplicates the order's payment |

The exact reasons are stored in `rejected_records.reasons`; raw values are stored as JSON.

## Review workflow

1. Run `python -m salespulse.cli quality` or open the dashboard's **Quality checks** tab.
2. Inspect failed checks, their failure counts, and the recommended action.
3. Query the affected rows; do not edit the database directly.
4. Fix the source file, then re-import it. The pipeline will insert/update only what changed.
5. Re-run the checks and confirm `25 / 25` passes before publishing reports.

The demo run ends with:

```text
Quality status: PASS
25 / 25 checks pass
0 critical failures
0 warnings
```

## Known limitations

- The checks validate the current database, not the upstream source system.
- `orders_future_dated` and `stuck_import_batches` use the machine clock; a backfill or timezone
  issue can produce a warning.
- `schema_version` checks presence, not equality with the application's expected version.
- Duplicate order events are a heuristic and require judgment.
- The quality layer cannot detect plausible but incorrect values, such as a wrong unit price within
  the allowed range. Source-system controls still matter.
- Rejected rows are not automatically corrected or retried; a human must fix and re-import.
