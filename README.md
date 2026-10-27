# SalesPulse

**Sales analytics and automated reporting for a fictional multi-region store.**

SalesPulse is an end-to-end analytics portfolio project built around a reproducible dataset, a
validated SQLite ingestion pipeline, reusable SQL analytics, a Streamlit dashboard, and scheduled-style
Excel/CSV reporting. Every number shown in this repository comes from the included synthetic data.

> **Synthetic data notice:** all customers, products, orders, payments, and returns are fictional.
> They are generated from a fixed random seed (`42`) and data version (`1.0.0`). No real customer,
> business, or financial data is included.

---

## Screenshots & Demo

| | |
|---|---|
| **Executive overview** — completed-order KPIs, trend, status split, monthly table | **Import validation** — dry run with accepted/rejected rows and row-level reasons |
| [![Executive overview](docs/screenshots/01_dashboard_overview.png)](docs/screenshots/01_dashboard_overview.png) | [![Dry-run validation](docs/screenshots/05_dry_run_validation.png)](docs/screenshots/05_dry_run_validation.png) |
| **Data quality** — 21 SQL checks plus 4 SQLite/runtime checks | **Excel export** — actual Product Performance sheet from the generated workbook |
| [![Data quality](docs/screenshots/11_data_quality.png)](docs/screenshots/11_data_quality.png) | [![Excel export](docs/screenshots/07_excel_export.png)](docs/screenshots/07_excel_export.png) |

The screenshots are genuine captures of the running dashboard and the generated workbook. See the
[full screenshot gallery and capture notes](docs/screenshots/README.md) for the complete set, including
product, customer, geographic, upload/profile, import-history, rejection, and workbook views.

### Demo snapshot (seed 42)

| Measure | Result |
|---|---:|
| Reporting window | 2025-01-03 → 2026-06-30 |
| Clean source rows | 200 customers · 42 products · 680 orders · 1,318 order items · 73 returns · 620 payments |
| Orders by status | 579 completed · 41 pending · 60 cancelled |
| Net revenue | **$121,391.03** |
| Gross sales / discounts / approved refunds | $136,848.28 / $9,636.28 / $5,821.55 |
| Average order value | **$209.66** |
| Purchasing customers / units sold | 184 / 2,389 |
| Cancellation rate / return rate | **8.82% / 4.19%** |
| Messy-row rejections retained with reasons | **43** across 6 datasets |
| Committed import batches | 12 (6 clean successes + 6 messy partials) |
| Quality checks | **25 / 25 pass** |
| Automated tests | **82 passing** |

The final demo database contains the clean business data plus one accepted, normalizable customer row
from the messy dataset; the other 43 messy rows are stored in `rejected_records`, not silently dropped.
That is why the database has 201 customers while the clean baseline has 200.

---

## Why this project

Most portfolio dashboards stop at a chart. SalesPulse focuses on the parts that make analytics
trustworthy:

- **Deterministic data** — clean and deliberately messy CSVs are reproducible byte-for-byte from a seed.
- **Validated ingestion** — exact schema checks, documented normalization, row-level rejection reasons,
  transactional writes, idempotent re-imports, and audit batches.
- **One financial definition** — revenue is defined once in SQL views and reused by every query, report,
  export, and dashboard page.
- **Reconciliation, not guesswork** — order-level and line-level revenue must agree; payment amounts must
  reconcile to net sales; returns and refunds are capped by database triggers.
- **A complete reporting workflow** — SQL analytics → CLI report → 19-sheet Excel workbook, 18 CSV
  sections plus SHA-256 manifest, Markdown sample, and a five-section Streamlit app.

No paid cloud services, Spark, or Airflow are required. The project is intentionally small enough to
run locally, but the patterns transfer to a warehouse-based stack.

---

## Architecture

```text
seed 42 + data version 1.0.0
            │
            ▼
  deterministic generator ──────────────► data/raw/clean/*.csv  (happy path)
            │                              data/raw/messy/*.csv (documented bad rows)
            ▼
  file → schema → row validation → database business rules
            │
            ├── rejection reasons ───────► import_batches + rejected_records
            │
            ▼
       SQLite database
       ├── dimensions: customers, products
       ├── facts: orders, order_items, returns, payments
       ├── audit: import_batches, rejected_records
       └── views: v_order_financials, v_order_line_financials
            │
            ├── 20 parameterized SQL analytics queries
            │        ├── Streamlit dashboard (5 sections, date filters, CSV downloads)
            │        └── report bundle ──► XLSX (19 sheets), CSV + manifest, Markdown
            │
            └── 25 data-quality / reconciliation checks
```

### Technology

| Layer | Tools |
|---|---|
| Language | Python 3.11+ |
| Data preparation | Pandas, NumPy |
| Storage | SQLite, SQLAlchemy 2.x |
| Analytics | Parameterized SQL, analytical views |
| Dashboard | Streamlit, Plotly |
| Reporting | openpyxl, CSV, Markdown |
| Quality | pytest, Ruff, SQL checks, SQLite `quick_check` and `foreign_key_check` |

---

## Quickstart

### 1. Create an environment and install

```bash
git clone https://github.com/elhussienysabry/SalesPulse.git
cd SalesPulse
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

`uv` works too:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

### 2. Run the complete demo

```bash
python -m salespulse.cli demo --reset --regenerate-data --with-messy
```

This command:

1. creates or resets `data/processed/salespulse.db`,
2. regenerates the clean and messy sample CSVs from seed `42`,
3. imports the six clean datasets in dependency order,
4. imports the six messy datasets to produce a documented rejection audit,
5. runs the 25 quality checks,
6. writes `output/sales_report.xlsx`, `output/csv/`, `output/import_summary.json`, and
   `docs/sample_report.md`.

Expected highlights:

```text
Quality summary: PASS (25/25 checks pass, 0 critical failures)
Demo complete. Start the dashboard with: streamlit run app.py
```

### 3. Start the dashboard

```bash
streamlit run app.py
```

Open <http://localhost:8501>.

For a clean-only database, omit `--with-messy`. To keep an existing database, omit `--reset`.

### 4. Run tests and lint

```bash
pytest -q
ruff check .
ruff format --check .
```

---

## Dashboard

SalesPulse has five sections in the sidebar, all backed by SQL queries against the live SQLite file.

### Overview

- Net revenue, completed orders, AOV, purchasing customers, cancellation rate, return rate.
- Revenue trend (monthly by default; daily when the selected range is 75 days or shorter).
- Order-status donut for all placed orders.
- Monthly performance table and month-over-month growth chart.
- CSV downloads for trend and monthly data.

### Product Performance

- KPI cards for product revenue, units sold, returned units, return rate, and products sold.
- Top products by net revenue and revenue by category.
- Category filter in the sidebar.
- Product table with revenue per unit and unit retention.
- Empty states when a filter has no matching data.

### Customer Analytics

- Purchasing, new, and returning customer counts.
- Average and top customer spend.
- Spending-band histogram and purchase-frequency distribution.
- Top-customer ranking and downloadable customer summary.
- Acquisition is defined by the customer's first-ever completed order. With the full date range
  selected, every purchasing customer naturally classifies as new; the dashboard states this explicitly.

### Geographic Analysis

- Revenue by region and order-volume-vs-revenue bubble view.
- Regional performance table with completed, cancelled, customer, AOV, cancellation-rate, and
  revenue-share metrics.
- Region is the order's shipping region.

### Data & Imports

Three tabs:

1. **Upload & validate** — choose a dataset, review expected columns, upload a CSV, inspect a
   data-quality profile (inferred types, missingness, duplicates), run a rolled-back dry run, then
   import valid rows. Rejections are downloadable and every committed batch is audited.
2. **Import history** — batch counts, row outcomes, latest batch, full batch table, and a filterable
   row-level rejection report.
3. **Quality checks** — 25 checks with severity, failures, status, detail, recommended action,
   database row counts, and reconciliation results.

Downloads are generated from the currently displayed database results and filtered tables. The app
shows explicit empty states when there is no database, no order data, no completed orders, or no data
for the selected filters.

---

## CLI

```bash
python -m salespulse.cli --help
```

| Command | Purpose |
|---|---|
| `init-db` | Create or update tables, views, indexes, triggers, and schema metadata |
| `seed-data` | Generate deterministic clean and messy CSVs (`--force` to overwrite) |
| `ingest FILE --dataset NAME` | Validate and import one CSV; supports `--dry-run` and `--summary-json` |
| `ingest-all --dir PATH` | Import all supported CSVs in dependency order |
| `report` | Print a text report; optional Markdown output and category filter |
| `export --format xlsx` | Write the styled 19-sheet Excel workbook |
| `export --format csv` | Write 18 CSV sections plus `report_manifest.json` |
| `quality [--export FILE]` | Run all checks and optionally export the audit CSV |
| `import-history [--json]` | Inspect committed batches |
| `demo` | One-command reproducible end-to-end run |

Useful options:

```bash
# Import one file and keep a machine-readable audit summary
python -m salespulse.cli ingest data/raw/messy/orders.csv \
  --dataset orders --summary-json output/orders_import.json

# Preview the messy file without writing anything
python -m salespulse.cli ingest data/raw/messy/orders.csv --dataset orders --dry-run

# Report for a subset of the data
python -m salespulse.cli report --from 2026-01-01 --to 2026-06-30 --category Electronics

# Regenerate the workbook and send quality output to a CSV
python -m salespulse.cli export --format xlsx --output output/sales_report.xlsx
python -m salespulse.cli quality --export output/data_quality.csv
```

---

## Data model

| Object | Type | Grain / purpose |
|---|---|---|
| `customers` | Dimension | One row per fictional customer |
| `products` | Dimension | One row per fictional product |
| `orders` | Fact | One row per order header; status is `completed`, `pending`, or `cancelled` |
| `order_items` | Fact | One row per product on an order; unique `(order_id, product_id)` |
| `returns` | Fact | One row per return request/decision against an order item |
| `payments` | Fact | At most one payment per order; amount must reconcile to net sales |
| `import_batches` | Audit | One row per committed or failed ingestion attempt with row counters (dry runs roll back and are not persisted) |
| `rejected_records` | Audit | Row-level rejection details and original raw JSON |
| `v_order_financials` | View | Order-level gross sales, discounts, net sales, approved refunds, net revenue |
| `v_order_line_financials` | View | Line-level version of the same financial definitions |

The complete column-level dictionary is in [docs/data_dictionary.md](docs/data_dictionary.md).

### Revenue rules in one place

- **Gross sales** = Σ quantity × unit price, before discounts.
- **Discounts** = Σ quantity × unit price × discount rate.
- **Net sales** = gross sales − discounts.
- **Approved refunds** = refunds from returns with status `approved` only.
- **Net revenue** = net sales − approved refunds, for **completed orders only**.
- Refunds are attributed to the **original order date**, not the return date.
- Cancellation rate = cancelled orders ÷ all placed orders.
- Return rate = approved returned units ÷ sold units on completed orders.
- AOV = net revenue ÷ completed orders.
- Money is rounded half-up to cents using a shared `+1e-9` epsilon in Python and SQL so order and
  line totals reconcile.

Full formulas, examples, and edge cases are in [docs/metric_definitions.md](docs/metric_definitions.md).

---

## Data generation and the messy dataset

The generator writes two parallel datasets under `data/raw/`:

| Dataset | Purpose | Rows |
|---|---|---|
| `clean/` | Happy-path data used for the business dashboard | 200 customers, 42 products, 680 orders, 1,318 items, 73 returns, 620 payments |
| `messy/` | Adds documented bad rows to demonstrate validation and rejection handling | 205 customers, 48 products, 689 orders, 1,327 items, 82 returns, 626 payments |

Messy-row expectations are part of the contract and are asserted in tests:

| Dataset | Expected rejections | Why |
|---|---:|---|
| customers | 4 | duplicate ID, missing email, invalid date, invalid email |
| products | 6 | duplicate ID, missing name, negative price, unknown category, cost > price, invalid active flag |
| orders | 9 | duplicate ID, unknown/missing customer, invalid/future/pre-signup date, invalid status/region, missing city |
| order_items | 9 | duplicate ID/pair, unknown order/product, missing IDs, invalid quantity/price/discount |
| returns | 9 | duplicate ID, unknown item, invalid quantity/refund/status/date, missing reason, cap violations |
| payments | 6 | duplicate payment ID/order (including a mismatched amount), unknown order, invalid method, negative amount, paid without date |
| **Total** | **43** | All stored with row numbers, reasons, and raw data |

One customer row uses a documented region alias (`europe` → `Europe`) and is accepted. That explains
the final database's 201 customers versus 200 clean customers. See
[docs/data_quality_rules.md](docs/data_quality_rules.md) for the complete rule set, aliases, and audit behavior.

Generated CSVs, the database, and exports are ignored by git; the manifests with SHA-256 hashes are
regenerated from the seed as well. The committed Markdown report and screenshots are documentation
artifacts, not data sources.

---

## Ingestion guarantees

1. **File checks:** UTF-8, non-empty, ≤ 25 MB, parseable CSV, at least one data row.
2. **Schema checks:** exact expected columns, reordered to the canonical order; missing or unexpected
   columns fail the batch before writing.
3. **Static row checks:** ID patterns, ISO dates, future-date ceiling, enum values, numeric ranges,
   decimal places, duplicate keys within the file, email normalization.
4. **Database business checks:** parent rows must exist; order customer/date are immutable; status may
   only move `pending → completed/cancelled`; existing order-item values are mutable only while the
   parent order is pending; returns require completed orders; payment amounts must match net sales
   within $0.01.
5. **Transactional write:** business rows, batch audit, and rejection records commit together. An
   unexpected failure rolls the whole import back and records a failed batch.
6. **Idempotent re-import:** identical rows are `unchanged`; changed mutable fields are `updated`; new
   rows are `inserted`. Re-importing the same file never duplicates business data.
7. **Dry run:** executes the full transaction and rolls it back; the UI reports what would be written.

Database constraints and triggers are a second line of defence for return quantities and refund caps.
See [sql/schema.sql](sql/schema.sql).

---

## Analytics and reporting

### SQL layer

- 20 named queries in [sql/analytics/](sql/analytics/), loaded by `salespulse/analytics.py`.
- Queries are parameterized (`:date_from`, `:date_to`, optional `:category`, `:limit`) and do not
  concatenate user input.
- Financial views centralize revenue recognition so charts, tables, exports, and quality checks agree.

### Excel workbook

`output/sales_report.xlsx` contains a formatted **Read Me** sheet plus 18 analytical sections, including
Overview, Order Status, Daily/Monthly Revenue, MoM revenue, Product/Category performance, customer and
regional analyses, quality results, import history, and rejected records.

The workbook includes brand styling, freeze panes, filters, print setup (fit-to-width), synthetic-data
labels, and spreadsheet-formula-injection protection. `output/csv/` provides the same sections as
UTF-8 CSVs plus a manifest with per-file SHA-256 hashes.

`docs/sample_report.md` is a human-readable Markdown snapshot from the demo run.

---

## Quality checks

The 25 checks combine 21 SQL checks with four database/runtime checks:

- referential integrity and duplicate keys,
- required values, enum values, quantities, prices, discounts, and refund ranges,
- future dates, date-sequence violations, and returns on non-completed orders,
- return-quantity and refund caps,
- payment mismatch and payments against cancelled orders,
- completed orders without items and possible duplicate order events,
- order-vs-line and component revenue reconciliation,
- stuck import batches,
- SQLite `PRAGMA quick_check`, `PRAGMA foreign_key_check`, schema version, and failed imports.

The demo run passes **25 / 25** with zero critical failures. Checks never mutate data; issues are
reported for review. See [docs/data_quality_rules.md](docs/data_quality_rules.md).

---

## Project structure

```text
salespulse/
├── app.py                       # Streamlit dashboard (all five sections + import workflow)
├── salespulse/
│   ├── analytics.py             # Parameterized query catalog and service
│   ├── cli.py                   # init/seed/ingest/report/export/quality/demo commands
│   ├── config.py                # Paths, seed, as-of date, environment overrides
│   ├── database.py              # Engine, schema initialization, integrity helpers
│   ├── dashboard_data.py        # KPI cards, formatting, filters, quality cards
│   ├── exports.py               # XLSX/CSV writers, manifests, injection protection
│   ├── ingestion.py             # Transactional ingests, audits, rejections
│   ├── profiling.py             # Upload profiling and CSV-bytes helpers
│   ├── quality.py               # SQL + SQLite quality checks and recommended actions
│   ├── reporting.py             # Report bundle, text and Markdown renderers
│   ├── schema.py                # Dataset columns, ingestion order, metadata
│   ├── synthetic_data.py        # Deterministic clean and messy generators
│   ├── transformations.py       # Canonical aliases, parsers, rounding
│   └── validation.py            # File/schema/row checks and rejection records
├── sql/
│   ├── schema.sql               # Tables, constraints, triggers, financial views
│   └── analytics/               # 20 named SQL queries in 9 files
├── tests/                       # 82 tests (validation, ingestion, analytics, quality, exports, CLI, app)
├── docs/                        # Metric definitions, dictionary, quality rules, screenshots
├── portfolio/                   # Case study, résumé bullets, demo script
├── data/                        # Generated CSVs and SQLite database (ignored by git)
└── output/                      # Generated exports (ignored by git)
```

---

## Documentation

- [Metric definitions](docs/metric_definitions.md) — formulas, filters, edge cases, snapshot values.
- [Data dictionary](docs/data_dictionary.md) — tables, columns, constraints, views, and CSV contracts.
- [Data quality rules](docs/data_quality_rules.md) — validation, normalization, rejection counts, checks.
- [Screenshot gallery](docs/screenshots/README.md) — all images, captions, and capture provenance.
- [Sample report](docs/sample_report.md) — Markdown report generated by the demo.
- [Portfolio case study](portfolio/case_study.md) — problem, approach, decisions, results.
- [Demo script](portfolio/demo_script.md) — a three-minute walkthrough with a 90-second version.
- [Résumé bullets](portfolio/resume_bullets.md) — concise, verifiable project claims.

---

## Design decisions and limitations

**SQLite instead of a cloud warehouse.** The project is deliberately local: it demonstrates SQL,
transactions, constraints, and reproducible analytics without cloud credentials. The SQL layer is
portable, but production-scale concurrent ingestion would move to a warehouse and a scheduler.

**Python instead of Spark/Airflow.** At this scale, a small Pandas validation pipeline is easier to
test and explain. The ingestion boundaries are still explicit enough to swap in orchestration later.

**Reject, don't repair.** Only documented whitespace, email-case, and categorical alias normalization
is automatic. Unknown values are rejected with reasons so a human can correct the source and re-import.

**Returns attributed to the order date.** This keeps revenue and refund reporting aligned to the
original sale, but means a late return can change a previously reported period when data is refreshed.
That behavior is intentional and documented.

**Full-history acquisition view.** Because the demo contains no history before the selected start date,
the default full range classifies all purchasing customers as new. The dashboard says so; a narrower
period or a dataset with prior history would populate the returning segment.

**Demo scale, not production scale.** The dataset is synthetic and bounded, the dashboard queries
SQLite directly, and there is no authentication. This is portfolio evidence, not a production deployment.

---

## Data source and license

All data is generated locally by [`salespulse/synthetic_data.py`](salespulse/synthetic_data.py) from
seed `42` and data version `1.0.0`. No third-party dataset, customer list, or uploaded business data
is redistributed. The code and generated sample data are released under the MIT License; see
[LICENSE](LICENSE).

Maintained by [@elhussienysabry](https://github.com/elhussienysabry).
