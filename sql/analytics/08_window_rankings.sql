-- Window-function rankings used by the portfolio and dashboard drill-downs.

-- name: monthly_revenue_rank
-- description: Calendar-month revenue rank and share within the period.
WITH monthly AS (
    SELECT
        substr(order_date, 1, 7) AS period,
        ROUND(SUM(net_revenue), 2) AS net_revenue,
        COUNT(*) AS completed_orders
    FROM v_order_financials
    WHERE status = 'completed'
      AND order_date BETWEEN :date_from AND :date_to
    GROUP BY substr(order_date, 1, 7)
)
SELECT
    period,
    net_revenue,
    completed_orders,
    RANK() OVER (ORDER BY net_revenue DESC) AS revenue_rank,
    ROUND(100.0 * net_revenue / NULLIF(SUM(net_revenue) OVER (), 0), 2)
        AS revenue_share_pct
FROM monthly
ORDER BY period;

-- name: product_category_rankings
-- description: Products ranked by revenue within their category.
WITH products AS (
    SELECT
        p.category,
        p.product_id,
        p.product_name,
        ROUND(SUM(p.net_revenue), 2) AS net_revenue,
        SUM(p.quantity) AS units_sold
    FROM v_order_line_financials p
    WHERE p.status = 'completed'
      AND p.order_date BETWEEN :date_from AND :date_to
      AND (:category IS NULL OR p.category = :category)
    GROUP BY p.category, p.product_id, p.product_name
)
SELECT
    category,
    product_id,
    product_name,
    net_revenue,
    units_sold,
    RANK() OVER (PARTITION BY category ORDER BY net_revenue DESC) AS rank_in_category,
    ROUND(
        100.0 * net_revenue / NULLIF(SUM(net_revenue) OVER (PARTITION BY category), 0),
        2
    ) AS category_revenue_share_pct
FROM products
ORDER BY category, rank_in_category, product_id;
