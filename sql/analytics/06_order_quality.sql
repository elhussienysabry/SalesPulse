-- Cancellation and return rates.
-- Return rate is approved returned units divided by units sold on completed
-- orders in the period. Returns are attributed to the original order date.

-- name: cancellation_and_return_rates
-- description: One-row operational quality summary for the selected period.
WITH order_scope AS (
    SELECT
        COUNT(*) AS total_placed_orders,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_orders,
        SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders
    FROM v_order_financials
    WHERE order_date BETWEEN :date_from AND :date_to
),
sold AS (
    SELECT
        COUNT(DISTINCT order_item_id) AS sold_lines,
        COALESCE(SUM(quantity), 0) AS sold_units,
        COALESCE(SUM(net_sales), 0) AS net_sales_before_returns
    FROM v_order_line_financials
    WHERE status = 'completed'
      AND order_date BETWEEN :date_from AND :date_to
),
return_scope AS (
    SELECT
        COUNT(DISTINCT r.return_id) AS approved_returns,
        COUNT(DISTINCT r.order_item_id) AS returned_lines,
        COALESCE(SUM(r.quantity), 0) AS returned_units,
        COALESCE(SUM(r.refund_amount), 0) AS refunds
    FROM returns r
    JOIN order_items oi ON oi.order_item_id = r.order_item_id
    JOIN orders o ON o.order_id = oi.order_id
    WHERE r.status = 'approved'
      AND o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
)
SELECT
    os.total_placed_orders,
    os.completed_orders,
    os.pending_orders,
    os.cancelled_orders,
    ROUND(100.0 * os.cancelled_orders / NULLIF(os.total_placed_orders, 0), 2)
        AS cancellation_rate_pct,
    s.sold_lines,
    s.sold_units,
    r.returned_lines,
    r.returned_units,
    r.approved_returns,
    ROUND(r.refunds, 2) AS refunds,
    ROUND(100.0 * r.returned_units / NULLIF(s.sold_units, 0), 2) AS return_rate_pct,
    ROUND(100.0 * r.returned_lines / NULLIF(s.sold_lines, 0), 2) AS returned_line_rate_pct,
    ROUND(s.net_sales_before_returns, 2) AS net_sales_before_returns,
    ROUND(r.refunds / NULLIF(s.net_sales_before_returns, 0) * 100.0, 2)
        AS refund_rate_pct
FROM order_scope os
CROSS JOIN sold s
CROSS JOIN return_scope r;
