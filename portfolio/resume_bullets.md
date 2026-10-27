# Résumé and portfolio copy

Verifiable claims for the SalesPulse project. Every number below is reproducible from the demo
database or generated outputs. All data is synthetic.

## One-line summary

Built an end-to-end sales analytics system with deterministic synthetic data, validated
transactional ingestion into SQLite, 20 reusable SQL analyses, a five-section Streamlit dashboard,
25 quality checks, and automated 19-sheet Excel/CSV reporting.

## Two-line summary

Designed and implemented a reproducible analytics pipeline that validates six relational CSV
datasets, rejects and audits bad rows with row-level reasons, and exposes shared revenue metrics
through SQL views. Delivered a Streamlit dashboard and a 19-sheet Excel workbook backed by 82
automated tests and 25 data-quality checks.

## Résumé bullets

### Data engineering

- Built a deterministic data generator producing six related CSV datasets (2,933 clean rows) plus a
  parallel messy dataset with 43 documented data-quality failures, reproducible from seed `42`.
- Designed a normalized SQLite schema with eight tables, two financial views, foreign keys, enum
  and range constraints, and four triggers enforcing return-quantity and refund caps.
- Implemented layered CSV validation (file, schema, static row, cross-table business rules) with
  row-level rejection reasons, raw-value audit, and a 25 MB upload limit.
- Built transactional, idempotent ingestion that commits business rows, batch audit, and rejections
  together; unexpected failures roll back completely and record a failed batch.
- Enforced business rules including immutable order customer/date, `pending → completed/cancelled`
  status transitions, completed-only returns, payment-to-net-sales reconciliation within $0.01, and
  cumulative return/refund caps.
- Created a 20-query parameterized SQL analytics layer covering revenue trends, MoM growth, product
  and category performance, customer acquisition/frequency, regional performance, and rankings.

### Analytics and reporting

- Delivered a five-section Streamlit dashboard (Overview, Product, Customer, Geographic, Data &
  Imports) with inclusive date filters, category filters, empty states, and downloads generated
  from the displayed SQL results.
- Centralized revenue recognition in two SQL views so the dashboard, Excel, CSV, Markdown, and
  quality checks all report the same net revenue (**$121,391.03** on the demo data).
- Automated a styled 19-sheet Excel workbook and 18 CSV sections plus a SHA-256 manifest, including
  print setup, freeze panes, filters, and spreadsheet-formula-injection protection.
- Added a Read Me sheet with report metadata, revenue definitions, headline KPIs, and a contents
  map with row counts and data lineage.

### Quality and testing

- Implemented 25 quality checks: 21 SQL checks plus SQLite `quick_check`, foreign-key integrity,
  schema version, and failed-import detection; the demo passes **25/25** with zero critical
  failures or warnings.
- Added reconciliation checks for order-vs-line revenue, revenue components, payment amounts,
  return quantities, and approved refunds.
- Wrote **82 pytest tests** covering validation, ingestion/idempotency, analytics, quality,
  reporting/exports, CLI, and Streamlit helpers; kept the codebase Ruff-clean.
- Produced 13 genuine screenshots of the dashboard, import workflow, rejection report, and generated
  workbook, with documented capture provenance and checklist mapping.

### Documentation

- Documented metric definitions, a column-level data dictionary, CSV contracts, quality rules,
  aliases, rejection counts, and a two-minute demo script.
- Made the project reproducible with a one-command demo:
  `python -m salespulse.cli demo --reset --regenerate-data --with-messy`.

## Compact project entry

**SalesPulse — Sales Analytics & Automated Reporting** | Python, Pandas, SQLite, SQLAlchemy, SQL,
Streamlit, Plotly, openpyxl, pytest

- End-to-end analytics system: deterministic source data → validated transactional ingestion →
  shared SQL views → dashboard and automated Excel/CSV reporting.
- Handles 2,933 clean rows across six related datasets plus 43 documented messy-row rejections with
  raw-value audit and row-level reasons.
- 20 parameterized SQL queries; 25/25 quality checks pass; 82 tests; 19-sheet Excel workbook.
- All data synthetic; no cloud services, Spark, or Airflow required.

## LinkedIn / portfolio blurb

> I built SalesPulse to practice the parts of analytics that a chart alone doesn’t show: validating
> messy source files, auditing rejected rows, keeping one revenue definition across every output,
> reconciling payments and returns, and automating recurring reports. It ingests six related
> datasets into SQLite, exposes 20 reusable SQL analyses through a Streamlit dashboard, and produces
> a 19-sheet Excel workbook plus CSV exports. The demo passes 25/25 quality checks and 82 tests, and
> everything is reproducible from a fixed seed. All data is synthetic.

## Skills demonstrated

| Area | Evidence |
|---|---|
| SQL | Normalized schema, constraints, indexes, triggers, two financial views, 20 named queries, window functions (`LAG`, `ROW_NUMBER`, `DENSE_RANK`), CTEs |
| Python | Pandas validation and transformation, SQLAlchemy 2.x, dataclasses, CLI design, deterministic generation |
| Data quality | File/schema/row/business validation, rejection audit, reconciliation checks, idempotency |
| Analytics | Revenue recognition, AOV, cancellation/return rates, new-vs-returning, frequency bands, regional share |
| Visualization | Streamlit, Plotly bar/line/pie/scatter charts, KPI cards, empty states, CSV downloads |
| Reporting | openpyxl styling and print setup, CSV manifests, Markdown rendering, formula-injection protection |
| Testing | pytest fixtures, in-memory and file databases, validation/ingestion/export/CLI/app tests, Ruff |
| Documentation | Metric definitions, data dictionary, quality rules, screenshot provenance, demo script |

## Honest framing

Use “synthetic,” “demo,” and “portfolio project” when describing the data. The project demonstrates
engineering patterns and reproducible results; it does not claim production traffic, real business
impact, cost savings, or a deployed multi-user service.
