-- Order volume, revenue, and average order value.
-- Completed orders are the revenue-recognised population. Other statuses are
-- reported separately so order counts are never mixed across definitions.

-- name: overview_metrics
-- description: Headline KPIs for completed orders in the selected period.
SELECT
    COUNT(*) AS completed_orders,
    COUNT(DISTINCT o.customer_id) AS unique_customers,
    COALESCE(SUM(o.unit_count), 0) AS units_sold,
    ROUND(COALESCE(SUM(o.gross_sales), 0), 2) AS gross_sales,
    ROUND(COALESCE(SUM(o.discount_amount), 0), 2) AS discounts,
    ROUND(COALESCE(SUM(o.refunds), 0), 2) AS refunds,
    ROUND(COALESCE(SUM(o.net_revenue), 0), 2) AS net_revenue,
    COALESCE(ROUND(SUM(o.net_revenue) / NULLIF(COUNT(*), 0), 2), 0.0) AS average_order_value
FROM v_order_financials o
WHERE o.status = 'completed'
  AND o.order_date BETWEEN :date_from AND :date_to;

-- name: order_status_breakdown
-- description: All placed orders by status, with recognised revenue only for completed.
SELECT
    o.status,
    COUNT(*) AS orders,
    COUNT(DISTINCT o.customer_id) AS unique_customers,
    ROUND(SUM(o.gross_sales), 2) AS item_value,
    ROUND(SUM(o.net_revenue), 2) AS recognised_net_revenue
FROM v_order_financials o
WHERE o.order_date BETWEEN :date_from AND :date_to
GROUP BY o.status
ORDER BY CASE o.status
    WHEN 'completed' THEN 1
    WHEN 'pending' THEN 2
    WHEN 'cancelled' THEN 3
    ELSE 4
END;

-- name: monthly_order_metrics
-- description: Monthly completed-order count and AOV.
SELECT
    substr(o.order_date, 1, 7) AS period,
    COUNT(*) AS completed_orders,
    ROUND(SUM(o.net_revenue), 2) AS net_revenue,
    ROUND(SUM(o.net_revenue) / NULLIF(COUNT(*), 0), 2) AS average_order_value
FROM v_order_financials o
WHERE o.status = 'completed'
  AND o.order_date BETWEEN :date_from AND :date_to
GROUP BY substr(o.order_date, 1, 7)
ORDER BY period;
