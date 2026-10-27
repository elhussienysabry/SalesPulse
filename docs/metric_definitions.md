# Metric definitions

This document is the reference for every business measure in SalesPulse. The same definitions are
implemented in [sql/schema.sql](../sql/schema.sql) and the queries under
[sql/analytics/](../sql/analytics/), then reused by the dashboard, reports, and exports.

> All data is synthetic. The demo snapshot uses seed `42`, data version `1.0.0`, and an order-date
> window from `2025-01-03` through `2026-06-30`.

## Conventions

- **Currency:** USD, displayed to two decimals.
- **Dates:** ISO-8601 `YYYY-MM-DD`; timestamp values are UTC ISO-8601 with a `Z` suffix.
- **Reporting window:** inclusive on both ends. An order dated exactly on `date_from` or `date_to`
  is included.
- **Order date is the reporting date.** Revenue, refunds, discounts, product, customer, and regional
  metrics all key off the original `orders.order_date`.
- **Revenue recognition:** only `orders.status = 'completed'` contributes revenue.
- **Placed orders** means all statuses: `completed`, `pending`, and `cancelled`.
- **Refunds** means approved returns only: `returns.status = 'approved'`. Requested and rejected
  returns have no revenue effect.
- **Money rounding:** half-up to cents. Python uses `round_money()` with a `+1e-9` epsilon; SQL uses
  matching `+1e-9` expressions. Quality checks allow a `$0.01` reconciliation tolerance.

## Query index

| File | Named queries |
|---|---|
| `01_revenue_trends.sql` | `daily_revenue`, `monthly_revenue`, `monthly_revenue_mom` |
| `02_order_metrics.sql` | `overview_metrics`, `order_status_breakdown`, `monthly_order_metrics` |
| `03_product_performance.sql` | `product_performance`, `category_performance`, `top_products_by_revenue`, `top_products_by_units` |
| `04_customer_analytics.sql` | `new_vs_returning`, `customer_purchase_summary`, `customer_frequency_distribution`, `top_customers` |
| `05_regional_performance.sql` | `regional_performance` |
| `06_order_quality.sql` | `cancellation_and_return_rates` |
| `07_data_quality_checks.sql` | `quality_checks` |
| `08_window_rankings.sql` | `monthly_revenue_rank`, `product_category_rankings` |
| `09_date_filtered_report.sql` | `date_filtered_orders` |

All date-filtered queries take `:date_from` and `:date_to`; product queries also accept an optional
`:category`; ranking queries accept a `:limit`.

---

## Revenue metrics

### Gross sales

```text
line gross_sales = ROUND(quantity × unit_price + 1e-9, 2)
order gross_sales = SUM(line gross_sales)
```

The order value is the sum of rounded line values, then rounded again to cents. `v_order_financials`
exposes `gross_sales` for all orders and `recognized_gross_sales` (zero unless completed).

### Discounts

```text
line discount = ROUND(quantity × unit_price × discount_rate + 1e-9, 2)
order discounts = SUM(line discount)
```

`discount_rate` is a decimal fraction between `0` and `0.90` (0%–90%).

### Net sales

```text
net_sales = gross_sales − discounts
```

This is the discounted merchandise value before returns. For non-completed orders it is reported in
the order-status context but **not** recognized as revenue.

### Approved refunds

```text
refunds = SUM(returns.refund_amount)
          where return.status = 'approved'
          and the return belongs to the order
```

- Refunds are capped at the discounted value of the line, both in ingestion and by SQLite triggers.
- Returned quantity is capped at the purchased quantity.
- Refunds are attributed to the **original order date**, not the return date.

### Net revenue (the headline revenue metric)

```text
net_revenue = net_sales − approved refunds     when status = 'completed'
            = 0                               otherwise
```

The dashboard labels this **Net revenue** and describes it as:

> Gross sales − discounts − approved refunds, completed orders only.

This is the revenue used by the Overview KPI, revenue trend, product/customer/regional revenue, AOV,
reporting bundle, Excel export, CSV exports, and Markdown report.

### Recognized revenue components

`v_order_financials` also exposes:

- `recognized_gross_sales` — gross sales only for completed orders,
- `recognized_discount_amount` — discounts only for completed orders,
- `is_revenue_recognized` — `1` for completed orders, otherwise `0`.

These prevent accidental mixing of placed-order values with recognized values.

---

## Order metrics

### Completed orders

```text
COUNT(*) FROM v_order_financials
WHERE status = 'completed'
  AND order_date BETWEEN :date_from AND :date_to
```

### Average order value (AOV)

```text
AOV = net revenue ÷ completed orders
```

Only completed orders are in both numerator and denominator. If there are no completed orders, the
overview query uses `0.0`; daily/monthly series return `NULL` for an empty group (no row). The dashboard
shows an explicit empty state rather than inventing a value.

### Cancellation rate

```text
cancellation_rate = cancelled orders ÷ all placed orders × 100
```

- Numerator: orders with status `cancelled`.
- Denominator: completed + pending + cancelled orders in the period.
- Pending orders are included in the denominator because they were placed.
- This is intentionally different from return rate; cancelled orders were never fulfilled.

### Order status mix

The status donut uses all placed orders and shows completed, pending, and cancelled. Its center value
is the total number of placed orders, not completed orders.

### Month-over-month (MoM) growth

```text
MoM % = (current month net revenue − previous month net revenue)
        ÷ previous month net revenue × 100
```

The previous month must be inside the selected reporting window. The first month in the window has a
null change; the query uses `LAG()` over monthly net revenue. A zero prior month yields `NULL`, not an
infinite growth claim.

### Daily vs monthly trend

The dashboard uses daily revenue when the selected range is 75 days or fewer; otherwise it uses monthly
revenue. The underlying daily and monthly queries always return completed-order data only.

---

## Product metrics

Product metrics use `v_order_line_financials`, filtered to completed orders in the period.

### Units sold

```text
units_sold = SUM(order_items.quantity)
```

Gross units before returns. This is a unit count, not a revenue measure.

### Returned units

```text
returned_units = SUM(approved return quantities) for the line
```

Only approved returns count. Requested or rejected returns do not reduce retention metrics.

### Product return rate

```text
product return rate = returned units ÷ units sold × 100
```

At the portfolio KPI level this is aggregated across all products on completed orders.

### Unit retention

```text
unit_retention_pct = (units sold − returned units) ÷ units sold × 100
```

This is the share of sold units not returned. It is capped at 100% by validation and triggers.

### Revenue per unit

```text
revenue_per_unit = product net revenue ÷ units sold
```

Because net revenue subtracts approved refunds but units sold is gross of returns, this is a
refund-adjusted revenue-per-gross-unit measure, not a contribution margin. Product cost is stored but
margin is not part of the dashboard dataset; no margin metric is claimed.

### Category performance

Same definitions as products, grouped by the product's category:

- orders = distinct completed orders containing the category,
- units sold = gross units,
- returned units = approved returned units,
- gross sales, discounts, refunds, net revenue,
- revenue per unit.

### Rankings

- `top_products_by_revenue`: `ROW_NUMBER()` ordered by net revenue descending, then product ID.
- `top_products_by_units`: `DENSE_RANK()` ordered by units sold descending.
- `product_category_rankings`: category-relative revenue ranking, with an optional category filter.
- `monthly_revenue_rank`: month ranking by net revenue.

Ties are deterministic because product ID is the final tiebreaker for the top-revenue query and the
category/region queries order by revenue then a stable key.

### Worked example: Smart Watch

| Field | Value |
|---|---:|
| Units sold | 105 |
| Returned units | 7 |
| Gross sales | $16,469.25 |
| Discounts | $996.03 |
| Approved refunds | $941.10 |
| Net revenue | $14,532.18 |
| Revenue per unit | $138.40 |
| Unit retention | 93.33% |

`$14,532.18 ÷ 105 = $138.40`; `(105 − 7) ÷ 105 = 93.33%`.

---

## Customer metrics

Customer metrics use completed orders in the reporting period, unless stated otherwise.

### Purchasing customers

```text
COUNT(DISTINCT customer_id)
FROM v_order_financials
WHERE status = 'completed'
  AND order_date BETWEEN :date_from AND :date_to
```

A customer who only has pending or cancelled orders is not a purchasing customer.

### New vs returning

A customer is **new** when their first-ever completed order in the database falls on or after
`date_from`. Otherwise they are **returning**. The lookup is based on all available history, not just
the selected window.

```text
first_completed_order = MIN(order_date)
                       FROM v_order_financials
                       WHERE status = 'completed'
                       GROUP BY customer_id

new       if first_completed_order >= date_from
returning if first_completed_order <  date_from
```

Implications:

- A customer counts as new when their first order is exactly on the start date.
- Only customers with at least one completed order in the selected period are included.
- With the full demo range selected and no pre-2025 history, **all** 184 purchasing customers are new;
  the dashboard states this rather than implying the returning segment is broken.

### Customer purchase summary

One row per purchasing customer with:

- completed orders in the period,
- units purchased (gross),
- net revenue,
- average order value = net revenue ÷ completed orders,
- first and last purchase date in the period,
- acquisition type (new/returning).

### Customer spending bands

The dashboard groups customers by their period net revenue:

| Band | Rule |
|---|---|
| `$0–100` | 0 ≤ net revenue < 100 |
| `$100–250` | 100 ≤ net revenue < 250 |
| `$250–500` | 250 ≤ net revenue < 500 |
| `$500–1k` | 500 ≤ net revenue < 1,000 |
| `$1k–2.5k` | 1,000 ≤ net revenue < 2,500 |
| `$2.5k+` | net revenue ≥ 2,500 |

Bands are lower-bound inclusive and upper-bound exclusive, with the lowest band including its lower
endpoint.

### Purchase frequency bands

| Band | Completed orders in period |
|---|---|
| `1 order` | exactly 1 |
| `2-3 orders` | 2 to 3 |
| `4-6 orders` | 4 to 6 |
| `7+ orders` | 7 or more |

For each band the dashboard shows customer count and average customer spend. In the demo snapshot:

| Band | Customers | Net revenue | Average spend |
|---|---:|---:|---:|
| 1 order | 31 | $6,293.29 | $203.01 |
| 2–3 orders | 85 | $41,574.40 | $489.11 |
| 4–6 orders | 57 | $58,501.80 | $1,026.35 |
| 7+ orders | 11 | $15,021.54 | $1,365.59 |

### Top customers

`DENSE_RANK()` ordered by period net revenue descending. Ties share a rank; the final order includes
customer ID for deterministic display.

### Average customer spend

```text
average customer spend = period net revenue ÷ purchasing customers
```

This is a per-customer mean, not AOV.

---

## Geographic metrics

Region is the order's **shipping region**, not the customer's profile region.

- **Regions active:** regions with at least one placed order in the period.
- **Orders:** all placed orders in the region.
- **Completed orders:** completed orders in the region.
- **Unique customers:** distinct customers with a completed order in the region/period.
- **Gross sales / discounts / refunds / net revenue:** completed-order values, using the same revenue
  view. Refunds are attributed to the original order date.
- **AOV:** regional net revenue ÷ regional completed orders.
- **Cancellation rate:** cancelled orders ÷ all placed orders in that region.
- **Revenue share:** regional net revenue ÷ total net revenue × 100.
- **Rank:** dense rank by regional net revenue.

---

## Operational quality metrics

These come from `cancellation_and_return_rates`:

### Return rate

```text
return rate = approved returned units ÷ sold units on completed orders × 100
```

- Numerator: sum of quantities from approved returns attached to completed orders in the period.
- Denominator: sum of quantities on completed order lines in the period.
- Returns are matched to the order date, so a return processed later still reduces the period in
  which the order was placed.

### Returned line rate

```text
returned_line_rate = distinct returned order items ÷ distinct sold order items × 100
```

This is a line-level view, not a unit-level view. A line with two returned units still counts once.

### Refund rate

```text
refund_rate = approved refunds ÷ net sales before returns × 100
```

The denominator is the discounted merchandise value of completed orders in the period before refunds.
This measures the refund burden against recognized merchandise value.

### Sold units and sold lines

- `sold_units` = sum of quantities on completed order lines.
- `sold_lines` = distinct order-item rows on completed orders.

---

## Data quality / reconciliation metrics

- **Failure count** in a quality check is the number of offending rows or conditions. Zero means pass.
- **Quality status** is `PASS` only when every check passes; any failure flips it to `FAIL`.
- **Critical failures** count failed checks with severity `critical`.
- **Warnings** count failed checks with severity `warning`.
- **Revenue reconciliation** compares order-level net revenue to the sum of line-level net revenue
  within `$0.01`.
- **Component reconciliation** checks `completed net sales − approved refunds = completed net revenue`
  within `$0.01`.
- **Payment reconciliation** allows a `$0.01` absolute difference between payment amount and order net
  sales.
- **Return caps** compare cumulative approved refunds to the line's discounted value with the same
  `+1e-9` rounding convention and a `$0.005` trigger tolerance.

The full check catalog and rule set are in [data_quality_rules.md](data_quality_rules.md).

---

## Snapshot values

The committed demo database produces:

| Metric | Value |
|---|---:|
| Reporting window | 2025-01-03 → 2026-06-30 |
| Placed orders | 680 |
| Completed / pending / cancelled | 579 / 41 / 60 |
| Cancellation rate | 8.82% |
| Net revenue | $121,391.03 |
| Gross sales | $136,848.28 |
| Discounts | $9,636.28 |
| Approved refunds | $5,821.55 |
| AOV | $209.66 |
| Purchasing customers | 184 |
| New / returning | 184 / 0 (full-range view) |
| Units sold | 2,389 |
| Returned units | 100 |
| Return rate | 4.19% |
| Top region | Middle East & Africa — $29,530.01 |
| Top product | Smart Watch — $14,532.18 |
| Top customer | Marlow Jensen — $2,338.51 |
| Quality checks | 25 / 25 pass |

Values are rounded for display; CSV exports preserve the database precision described above.

---

## Edge cases and caveats

1. **Empty period:** completed-order metrics are zero/blank and the dashboard shows an empty state.
   The database is not changed.
2. **No completed orders but placed orders exist:** status donut still shows placed orders; revenue,
   AOV, customer, product, and regional revenue metrics are empty/zero.
3. **Refund after the period:** if an approved refund exists against an in-period order, it reduces that
   order's period revenue even if the return date is later. This is intentional accrual-style
   attribution.
4. **Pending order becomes cancelled:** order item values remain visible in placed-order status context
   but never enter recognized revenue.
5. **Product cost:** stored for completeness, but the dashboard does not claim gross margin because
   the metric set is revenue-focused.
6. **Date filters:** both endpoints are inclusive; the dashboard derives its bounds from the orders table
   and refuses invalid or reversed ranges.
7. **Synthetic distributions:** the data is deterministic but not a statistical simulation of a real
   retailer. Use it to demonstrate pipeline behavior, not to forecast real demand.
