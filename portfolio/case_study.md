# SalesPulse — sales analytics and automated reporting

**A reproducible, end-to-end analytics project: deterministic source data → validated SQLite
warehouse → reusable SQL metrics → Streamlit dashboard → automated Excel/CSV reporting.**

> **All data is synthetic.** SalesPulse is a portfolio project built to demonstrate analytics
> engineering practices without using real customer or business data.

## At a glance

| | |
|---|---|
| **Role** | Solo design and build |
| **Stack** | Python 3.11, Pandas, NumPy, SQLite, SQLAlchemy, SQL, Streamlit, Plotly, openpyxl, pytest, Ruff |
| **Scope** | Data generation, schema design, validation, transactional ingestion, analytics SQL, dashboard, reporting, testing, documentation |
| **Data** | 6 relational datasets; 2,933 clean rows; a parallel messy dataset with 43 documented rejections |
| **Outputs** | 20 named SQL queries, 5 dashboard sections, a 19-sheet Excel workbook, 18 CSV sections plus a hash manifest, and a Markdown report |
| **Quality** | 25/25 quality checks pass; 82 automated tests |
| **Repo** | Code, SQL, tests, docs, and genuine screenshots — no generated database or large data committed |

## The problem

A dashboard is only as trustworthy as the pipeline behind it. Many portfolio projects start with a
clean CSV and stop at a chart, which hides the hard parts of analytics work:

- What happens when source rows are duplicated, malformed, or reference missing parents?
- Where is revenue defined, and does every chart, export, and quality check use the same definition?
- How do you prove that a re-import did not duplicate data or silently drop bad rows?
- How do you make a demo reproducible months later?

SalesPulse was built to answer those questions in a small, inspectable system.

## What I built

### 1. Deterministic source data

- A seeded generator (`seed=42`, data version `1.0.0`) writes byte-identical CSVs for six datasets:
  customers, products, orders, order_items, returns, and payments.
- A **clean** dataset demonstrates the happy path; a **messy** dataset adds 43 documented bad rows
  while retaining every clean row.
- Manifests record row counts and SHA-256 hashes. Generated data is gitignored and regenerated on
  demand.
- Orders span 2025-01-03 through 2026-06-30 and include completed, pending, and cancelled states.

### 2. Normalized SQLite schema with financial views

- Eight tables: two dimensions, four facts, and two audit tables.
- Primary keys, foreign keys, enum checks, date checks, numeric ranges, uniqueness, and payment
  consistency are enforced in the schema.
- Two analytical views centralize revenue recognition:
  - `v_order_financials` — one row per order,
  - `v_order_line_financials` — one row per order line.
- Four triggers enforce cumulative return-quantity and refund caps for direct SQL writes.
- `PRAGMA foreign_keys = ON` is set on every connection.

### 3. Validation and transactional ingestion

The pipeline has explicit layers:

1. **File gate** — exists, non-empty, UTF-8, ≤ 25 MB, parseable, at least one data row.
2. **Schema gate** — exact expected columns; missing or unexpected columns fail the batch.
3. **Static validation** — ID patterns, ISO dates, future-date ceiling, allow-lists, ranges,
   decimal places, duplicate keys, email normalization.
4. **Cross-table business rules** — parent rows must exist; order customer/date are immutable;
   status may only move `pending → completed/cancelled`; returns require completed orders; payment
   amounts must reconcile to net sales within $0.01.
5. **Transactional write** — business rows, batch audit, and rejection details commit together.
   Unexpected failures roll back the entire batch and record a failed audit row.
6. **Idempotent re-import** — identical rows are `unchanged`, changed mutable fields are `updated`,
   new rows are `inserted`. Re-importing the same file does not duplicate business data.

The design principle is **reject, don't repair**: only documented whitespace, email-case, and
categorical-alias normalization is automatic. Everything else is rejected with a row number, the
raw values, and a reason.

### 4. Analytics layer

- 20 named, parameterized SQL queries across nine files.
- Date filters (`:date_from`, `:date_to`), optional category filters, and limits are bound
  parameters — no concatenated user input.
- Analyses cover revenue trends, MoM growth, order status, product/category performance, customer
  acquisition and frequency, regional performance, cancellation/return rates, rankings, and data
  quality.
- Python services load the SQL from files and return typed DataFrames; the dashboard, reports, and
  exports all share the same query catalog.

### 5. Dashboard

Five Streamlit sections, all backed by live SQL queries:

- **Overview** — revenue, orders, AOV, customers, cancellation/return rates, trend, status mix,
  monthly table.
- **Product Performance** — KPIs, top products, category revenue, product table, category filter.
- **Customer Analytics** — new vs. returning, spending bands, purchase frequency, top customers,
  downloadable customer summary.
- **Geographic Analysis** — regional revenue, AOV, cancellation rate, revenue share, and a
  volume-vs-revenue view.
- **Data & Imports** — upload → profile → dry run → import, import history, rejection report, and
  the 25 quality checks.

The UI includes inclusive date filters, explicit empty states, CSV downloads generated from the
displayed results, a 25 MB upload limit, and a clearly labelled synthetic-data badge.

### 6. Automated reporting

- **Excel:** a styled 19-sheet workbook with a Read Me, 18 analytical sections, freeze panes,
  filters, print setup (A4, fit-to-width, landscape data sheets, repeated header rows), and
  spreadsheet-formula-injection protection.
- **CSV:** the same 18 sections as UTF-8 CSVs plus `report_manifest.json` with per-file SHA-256
  hashes.
- **Markdown:** a human-readable sample report generated by the demo.
- **CLI:** `init-db`, `seed-data`, `ingest`, `ingest-all`, `report`, `export`, `quality`,
  `import-history`, and a one-command `demo`.

### 7. Quality and tests

- 25 checks: 21 SQL checks plus SQLite `quick_check`, foreign-key integrity, schema version, and
  failed-import detection.
- Checks are read-only and return a failure count, severity, detail, and recommended action.
- 20 critical checks cover orphan rows, duplicate keys, invalid statuses/ranges, date-sequence
  errors, return/refund caps, payment mismatches, completed orders without lines, and revenue
  reconciliation. Five warnings cover possible duplicate events, future dates, failed imports,
  schema metadata, and stuck batches.
- 82 pytest tests cover validation, ingestion/idempotency, analytics, quality, reporting/exports,
  CLI, and Streamlit helpers.
- Ruff is used for linting and formatting checks.

## Architecture

```text
seed 42 + data version 1.0.0
        │
        ▼
deterministic generator ──────► data/raw/clean/*.csv
        │                       data/raw/messy/*.csv
        ▼
file → schema → row validation → business rules → SQLite transaction
        │                                      │
        │                                      ├── import_batches
        │                                      └── rejected_records
        ▼
SQLite database
├── customers, products
├── orders, order_items, returns, payments
└── v_order_financials, v_order_line_financials
        │
        ├── 20 SQL analytics queries
        │      ├── Streamlit dashboard (5 sections)
        │      └── report bundle
        │             ├── XLSX (19 sheets)
        │             ├── 18 CSVs + SHA-256 manifest
        │             └── Markdown report
        │
        └── 25 quality checks
```

## Key decisions and trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| SQLite instead of a cloud warehouse | Zero setup, easy to inspect, strong transactional guarantees for the demo | Not designed for concurrent production ingestion; the SQL would move to a warehouse at scale |
| Python/Pandas instead of Spark/Airflow | The dataset is small; explicit validation is easier to test and explain | No distributed processing or scheduler; orchestration would be added for production |
| Revenue defined once in SQL views | Every chart, report, export, and check uses the same formula | Views must be updated carefully when definitions change |
| Refunds attributed to the original order date | Keeps revenue and refund reporting aligned to the sale | A late return can change a previously reported period on refresh |
| Reject, don't repair | Preserves trust and makes bad source rows visible | Requires a human correction step |
| Dry run rolls back | Shows exactly what would be written without side effects | Dry runs are not persisted in the audit history |
| Warnings separated from critical checks | Avoids blocking reports for heuristics and operational noise | Requires judgment on warning review |
| 25 MB upload limit | Protects the local app and keeps imports fast | Not intended for large files |
| Synthetic data | No privacy or licensing concerns; fully reproducible | Does not model real seasonality or customer behavior |

## Results

All figures below come from the committed demo database and generated outputs.

| Measure | Result |
|---|---:|
| Clean source rows | 2,933 |
| Messy source rows | 2,977 |
| Documented messy-row rejections | 43 |
| Accepted normalizable messy customer | 1 |
| Final customers / products / orders | 201 / 42 / 680 |
| Completed / pending / cancelled orders | 579 / 41 / 60 |
| Net revenue | $121,391.03 |
| Gross sales / discounts / approved refunds | $136,848.28 / $9,636.28 / $5,821.55 |
| Average order value | $209.66 |
| Purchasing customers / units sold | 184 / 2,389 |
| Cancellation rate / return rate | 8.82% / 4.19% |
| Committed import batches | 12 |
| Quality checks | 25/25 pass |
| Automated tests | 82 passing |
| SQL analytics queries | 20 |
| Excel sheets / CSV sections | 19 / 18 |

The final database has 201 customers because one messy customer row used an accepted region alias;
the other 43 messy rows are stored in `rejected_records`.

## Evidence

- [Root README](../README.md) — setup, architecture, commands, demo snapshot.
- [Metric definitions](../docs/metric_definitions.md) — formulas, filters, edge cases, snapshot.
- [Data dictionary](../docs/data_dictionary.md) — tables, columns, constraints, CSV contracts.
- [Data-quality rules](../docs/data_quality_rules.md) — validation layers, aliases, rejection
  catalog, all 25 checks.
- [Screenshot gallery](../docs/screenshots/README.md) — 13 genuine captures with capture notes.
- [Sample report](../docs/sample_report.md) — Markdown output from the demo.
- [Tests](../tests/) — validation, ingestion, analytics, quality, exports, CLI, app helpers.
- [Schema](../sql/schema.sql) — tables, views, indexes, triggers.

## Limitations and next steps

**Current limitations**

- Synthetic data and a local, single-user SQLite database.
- No authentication, scheduler, or cloud deployment.
- No incremental/CDC ingestion; imports are file-based snapshots.
- The quality layer cannot detect plausible-but-wrong values inside allowed ranges.
- The full-history demo classifies all purchasing customers as new; a dataset with prior history
  would populate the returning segment.

**Next steps**

- Move the SQL layer to a warehouse (PostgreSQL/Snowflake/BigQuery) and add dbt-style tests.
- Add Airflow or a scheduler for recurring imports and report delivery.
- Add CI to run pytest, Ruff, and the demo end to end on every push.
- Add authentication and row-level access for a hosted dashboard.
- Model returns by processing date as a secondary view to complement order-date attribution.

## Links

- Source: repository root
- Dashboard: `streamlit run app.py` after the demo
- One-command demo:

  ```bash
  python -m salespulse.cli demo --reset --regenerate-data --with-messy
  ```

- Verification:

  ```bash
  pytest -q
  ruff check .
  ```
