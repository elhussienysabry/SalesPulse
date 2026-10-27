-- Daily and monthly revenue trends.
-- Scope: completed orders. Refunds are attributed to the original order date.
-- Revenue includes all approved refunds against orders in the selected period.

-- name: daily_revenue
-- description: Daily gross sales, discounts, refunds, net revenue, and AOV.
SELECT
    o.order_date AS period,
    COUNT(*) AS completed_orders,
    ROUND(SUM(o.gross_sales), 2) AS gross_sales,
    ROUND(SUM(o.discount_amount), 2) AS discounts,
    ROUND(SUM(o.refunds), 2) AS refunds,
    ROUND(SUM(o.net_revenue), 2) AS net_revenue,
    ROUND(SUM(o.net_revenue) / NULLIF(COUNT(*), 0), 2) AS average_order_value
FROM v_order_financials o
WHERE o.status = 'completed'
  AND o.order_date BETWEEN :date_from AND :date_to
GROUP BY o.order_date
ORDER BY o.order_date;

-- name: monthly_revenue
-- description: Monthly gross sales, discounts, refunds, net revenue, and AOV.
SELECT
    substr(o.order_date, 1, 7) AS period,
    COUNT(*) AS completed_orders,
    ROUND(SUM(o.gross_sales), 2) AS gross_sales,
    ROUND(SUM(o.discount_amount), 2) AS discounts,
    ROUND(SUM(o.refunds), 2) AS refunds,
    ROUND(SUM(o.net_revenue), 2) AS net_revenue,
    ROUND(SUM(o.net_revenue) / NULLIF(COUNT(*), 0), 2) AS average_order_value
FROM v_order_financials o
WHERE o.status = 'completed'
  AND o.order_date BETWEEN :date_from AND :date_to
GROUP BY substr(o.order_date, 1, 7)
ORDER BY period;

-- name: monthly_revenue_mom
-- description: Month-over-month revenue change within the selected range (LAG window).
WITH monthly AS (
    SELECT
        substr(o.order_date, 1, 7) AS period,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue,
        COUNT(*) AS completed_orders
    FROM v_order_financials o
    WHERE o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
    GROUP BY substr(o.order_date, 1, 7)
),
with_previous AS (
    SELECT
        period,
        net_revenue,
        completed_orders,
        LAG(net_revenue) OVER (ORDER BY period) AS previous_month_revenue
    FROM monthly
)
SELECT
    period,
    net_revenue,
    completed_orders,
    previous_month_revenue,
    ROUND(net_revenue - previous_month_revenue, 2) AS revenue_change,
    ROUND(
        100.0 * (net_revenue - previous_month_revenue)
        / NULLIF(previous_month_revenue, 0),
        2
    ) AS mom_growth_pct
FROM with_previous
ORDER BY period;
