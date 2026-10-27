-- Regional performance.
-- Revenue is recognised for completed orders only. The cancellation rate uses
-- all placed orders as its denominator so it is not confused with return rate.

-- name: regional_performance
-- description: Orders, revenue, AOV, and cancellations by shipping region.
WITH regional AS (
    SELECT
        o.shipping_region,
        COUNT(*) AS all_orders,
        SUM(CASE WHEN o.status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
        SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders,
        COUNT(DISTINCT CASE WHEN o.status = 'completed' THEN o.customer_id END)
            AS unique_customers,
        ROUND(SUM(o.recognized_gross_sales), 2) AS gross_sales,
        ROUND(SUM(o.recognized_discount_amount), 2) AS discounts,
        ROUND(SUM(o.refunds), 2) AS refunds,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue,
        ROUND(
            SUM(o.net_revenue) / NULLIF(SUM(CASE WHEN o.status = 'completed' THEN 1 ELSE 0 END), 0),
            2
        ) AS average_order_value,
        ROUND(
            100.0 * SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*),
            2
        ) AS cancellation_rate_pct
    FROM v_order_financials o
    WHERE o.order_date BETWEEN :date_from AND :date_to
    GROUP BY o.shipping_region
)
SELECT
    shipping_region,
    all_orders,
    completed_orders,
    cancelled_orders,
    unique_customers,
    gross_sales,
    discounts,
    refunds,
    net_revenue,
    average_order_value,
    cancellation_rate_pct,
    ROUND(100.0 * net_revenue / NULLIF(SUM(net_revenue) OVER (), 0), 2)
        AS revenue_share_pct,
    DENSE_RANK() OVER (ORDER BY net_revenue DESC) AS revenue_rank
FROM regional
ORDER BY net_revenue DESC, shipping_region;
