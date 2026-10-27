# SalesPulse demo script

A three-to-five minute walkthrough for a portfolio review, interview, or screen recording. All
figures are from the synthetic demo database. Say that early and clearly.

## Pre-demo checklist

```bash
# From the repository root
python -m salespulse.cli demo --reset --regenerate-data --with-messy
streamlit run app.py
```

Before you present, confirm:

- [ ] The dashboard opens at <http://localhost:8501>.
- [ ] The sidebar shows the full range, **2025/01/03 – 2026/06/30**.
- [ ] **Overview** shows **$121,391.03** net revenue and **579** completed orders.
- [ ] **Data & Imports → Quality checks** shows **25 / 25** pass.
- [ ] `output/sales_report.xlsx` is open in a spreadsheet app (or have the PDF preview ready).
- [ ] You have `data/raw/messy/orders.csv` ready to upload.
- [ ] You are not showing a real customer, employer, or confidential dataset.

## The 3-minute script

### 0:00 — Frame the project

> “SalesPulse is an end-to-end sales analytics system built on synthetic data. The goal was not
> just to build a dashboard, but to show the pipeline behind it: deterministic data, validated
> ingestion, reusable SQL metrics, quality checks, and automated Excel and CSV reporting.
> Everything you see is reproducible from seed 42, and all data is fictional.”

Open the repository README and point to the architecture diagram and the demo snapshot table.

### 0:20 — Overview

Click **Overview** in the sidebar.

> “The headline metric is net revenue: gross sales minus discounts minus approved refunds, for
> completed orders only. That definition lives in one SQL view, so the dashboard, the Excel
> workbook, the CSV exports, and the quality checks all use the same number.”

Point to the six KPI cards and the order-status donut.

> “The donut uses all placed orders, including pending and cancelled, because it is an operational
> view. Revenue metrics use only completed orders. The sidebar dates are inclusive.”

Point to the revenue trend and the monthly table.

> “The trend switches to daily when the selected range is 75 days or shorter. The monthly table
> includes gross sales, discounts, refunds, net revenue, and AOV.”

### 0:50 — Product performance

Click **Product Performance**.

> “Products are ranked by net revenue after refunds. Units sold are gross units, and unit retention
> subtracts only approved returns. The top product is Smart Watch at $14,532.18 net revenue.”

Hover the top-products bar chart; point to the category chart and the product table.

> “The category filter is in the sidebar and is applied in SQL, not in the browser.”

### 1:10 — Customer analytics

Click **Customer Analytics**.

> “This page answers who buys, how often, and how much. There are 184 purchasing customers in the
> period. All of them classify as new because the demo has no history before the selected start
> date — the caption says that explicitly rather than implying the returning segment is broken.”

Point to average customer spend (**$659.73**) and top customer spend (**$2,338.51**), then the
spending bands and frequency chart.

> “The customer table is downloadable at full precision.”

### 1:30 — Geographic analysis

Click **Geographic Analysis**.

> “Region is the order’s shipping region, not the customer’s profile region. Middle East & Africa
> leads with $29,530.01, about 24% of net revenue. Cancellation rate uses all placed orders as its
> denominator; return rate is a separate unit-based measure.”

Point to the regional table and the volume-vs-revenue bubble view.

### 1:45 — Data quality

Click **Data & Imports → Quality checks**.

> “There are 25 checks: 21 SQL checks plus SQLite quick_check, foreign-key integrity, schema
> version, and failed-import detection. The demo passes 25 out of 25, with zero critical failures
> and zero warnings. The checks are read-only; they report issues for review rather than repairing
> data.”

Point to a few check names, then the **Recommended action** column.

### 2:00 — Import a deliberately messy file

Click **Upload & validate**.

> “This is the part most portfolio projects skip. I’m going to upload the messy orders file — it
> contains all 680 clean orders plus nine deliberate problems.”

Keep the dataset as **orders**, upload `data/raw/messy/orders.csv`, and wait for the profile.

> “The profile shows 689 rows, seven columns, two missing cells, and zero exact duplicate rows.
> That’s the raw file, before business validation.”

Scroll to **Data-quality profile** and point to `customer_id` and `shipping_city` missing values.
Optionally open **Expected schema**.

Click **Validate file (dry run)**.

> “The dry run executes the full transaction and rolls it back. It accepted 680 rows and rejected
> nine, with zero writes now. The rejected rows include a duplicate order, an unknown customer, a
> missing customer, an invalid date, a future date, a pre-signup date, an invalid status, an invalid
> region, and a missing city.”

Point to the before/after panel and the rejection sample.

> “If I clicked Import valid rows, the valid 680 would be unchanged and the nine would be stored in
> the rejection audit with row numbers, reasons, and raw JSON. Re-importing the same file is
> idempotent — it does not duplicate business rows.”

### 2:40 — Import history and rejections

Click **Import history**.

> “Twelve committed batches: six clean successes and six messy partials. 5,910 rows processed, 43
> rejections retained. Every batch stores the file SHA-256 and row counters.”

Scroll to **Rejection report**; keep **All rejected records**.

> “This is the row-level audit. The raw JSON is preserved, so a human can see exactly what the
> source looked like. Nothing was silently dropped.”

### 3:00 — Excel and CSV reporting

Open `output/sales_report.xlsx` on the **Read Me** sheet.

> “The same SQL report bundle produces a 19-sheet Excel workbook with a Read Me, 18 analytical
> sections, print setup, filters, and formula-injection protection. The Read Me records the period,
> revenue definition, headline KPIs, and the contents map.”

Switch to **Product Performance**.

> “This is the actual Product Performance sheet, not a mockup. The same data is available as 18
> UTF-8 CSVs plus a SHA-256 manifest.”

Optionally show `output/import_summary.json` and the 43 rejections.

### 3:20 — Close

> “The project includes 82 tests, Ruff checks, 25 quality checks, and a one-command reproducible
> demo. The main limitations are deliberate: synthetic data, local SQLite, no scheduler or auth.
> The patterns — validation, transactional ingestion, shared metric definitions, reconciliation,
> and automated reporting — are the parts that transfer to a production warehouse.”

## 90-second version

If time is short:

1. **Overview** — net revenue, completed orders, the one revenue definition.
2. **Data quality** — 25/25, critical vs. warning.
3. **Upload messy orders.csv → dry run** — 689 read / 680 accepted / 9 rejected / 0 writes.
4. **Import history → rejection report** — 43 audited rows with raw JSON.
5. **Excel Read Me + Product Performance** — the same metrics in a formatted deliverable.
6. Close with tests and the one-command demo.

Skip Product, Customer, and Geographic pages, or mention them in one sentence each.

## Questions to expect

**“Is this real data?”**
No. Every customer, product, order, payment, and return is synthetic and generated from a fixed
seed. The dashboard and workbook both carry a synthetic-data label.

**“Why SQLite?”**
It makes the project self-contained and easy to inspect. The SQL layer is portable; a production
version would move to a warehouse and add orchestration and access control.

**“Why not repair bad rows automatically?”**
Because silent repair destroys trust. Only whitespace, email case, and documented categorical
aliases are normalized. Everything else is rejected with a reason so the source can be fixed.

**“How do you know the revenue numbers reconcile?”**
Two checks compare order-level net revenue to line-level totals and verify that net sales minus
approved refunds equals net revenue, both within $0.01. Payment amounts are also reconciled to
order net sales.

**“What happens on a failed import?”**
The entire transaction rolls back, a `failed` batch is recorded with the error, and no business rows
are partially written. Dry runs also roll back but do not persist an audit row.

**“What would you change at production scale?”**
Move to a warehouse, add a scheduler/orchestrator, CI, authentication, incremental ingestion, and
dbt-style tests. Keep the same separation between raw validation, business rules, shared metrics,
and reporting.

**“Why are all customers new?”**
The demo has no completed-order history before 2025-01-03, so every purchasing customer’s first
completed order falls inside the full range. Selecting a narrower period would create a returning
segment if prior history existed. The dashboard states this explicitly.

## Do-not-claim list

Keep the demo honest:

- Do **not** call the data real or anonymized; it is synthetic.
- Do **not** claim production scale, uptime, or concurrent-user support.
- Do **not** claim business impact such as saved hours or increased revenue; the project measures
  engineering behavior, not a real business outcome.
- Do **not** claim the Excel screenshots are separate designs; they are rasterizations of the
  generated workbook.
- Do **not** claim the screenshots come from a different product; they are captures of this
  application and the workbook it generates.
