-- Product and category performance.
-- Products are counted only on completed orders. Units sold are gross units
-- before approved returns; returns reduce net revenue and are shown separately.

-- name: product_performance
-- description: Product sales, refunds, unit retention, and revenue per unit.
SELECT
    p.product_id,
    p.product_name,
    p.category,
    COUNT(DISTINCT p.order_id) AS orders,
    SUM(p.quantity) AS units_sold,
    SUM(p.returned_units) AS returned_units,
    ROUND(SUM(p.gross_sales), 2) AS gross_sales,
    ROUND(SUM(p.discount_amount), 2) AS discounts,
    ROUND(SUM(p.refunds), 2) AS refunds,
    ROUND(SUM(p.net_revenue), 2) AS net_revenue,
    ROUND(SUM(p.net_revenue) / NULLIF(SUM(p.quantity), 0), 2) AS revenue_per_unit,
    ROUND(
        100.0 * (SUM(p.quantity) - SUM(p.returned_units)) / NULLIF(SUM(p.quantity), 0),
        2
    ) AS unit_retention_pct
FROM v_order_line_financials p
WHERE p.status = 'completed'
  AND p.order_date BETWEEN :date_from AND :date_to
  AND (:category IS NULL OR p.category = :category)
GROUP BY p.product_id, p.product_name, p.category
ORDER BY net_revenue DESC, p.product_id
;

-- name: category_performance
-- description: Revenue, units, and refunds by product category.
SELECT
    p.category,
    COUNT(DISTINCT p.order_id) AS orders,
    SUM(p.quantity) AS units_sold,
    SUM(p.returned_units) AS returned_units,
    ROUND(SUM(p.gross_sales), 2) AS gross_sales,
    ROUND(SUM(p.discount_amount), 2) AS discounts,
    ROUND(SUM(p.refunds), 2) AS refunds,
    ROUND(SUM(p.net_revenue), 2) AS net_revenue,
    ROUND(SUM(p.net_revenue) / NULLIF(SUM(p.quantity), 0), 2) AS revenue_per_unit
FROM v_order_line_financials p
WHERE p.status = 'completed'
  AND p.order_date BETWEEN :date_from AND :date_to
  AND (:category IS NULL OR p.category = :category)
GROUP BY p.category
ORDER BY net_revenue DESC;

-- name: top_products_by_revenue
-- description: Top products by net revenue with a row-number ranking.
WITH ranked AS (
    SELECT
        p.product_id,
        p.product_name,
        p.category,
        SUM(p.quantity) AS units_sold,
        ROUND(SUM(p.net_revenue), 2) AS net_revenue,
        ROW_NUMBER() OVER (ORDER BY SUM(p.net_revenue) DESC, p.product_id) AS revenue_rank
    FROM v_order_line_financials p
    WHERE p.status = 'completed'
      AND p.order_date BETWEEN :date_from AND :date_to
      AND (:category IS NULL OR p.category = :category)
    GROUP BY p.product_id, p.product_name, p.category
)
SELECT *
FROM ranked
WHERE revenue_rank <= :limit
ORDER BY revenue_rank;

-- name: top_products_by_units
-- description: Top products by units sold with a dense-rank window.
WITH ranked AS (
    SELECT
        p.product_id,
        p.product_name,
        p.category,
        SUM(p.quantity) AS units_sold,
        ROUND(SUM(p.net_revenue), 2) AS net_revenue,
        DENSE_RANK() OVER (ORDER BY SUM(p.quantity) DESC) AS units_rank
    FROM v_order_line_financials p
    WHERE p.status = 'completed'
      AND p.order_date BETWEEN :date_from AND :date_to
      AND (:category IS NULL OR p.category = :category)
    GROUP BY p.product_id, p.product_name, p.category
)
SELECT *
FROM ranked
WHERE units_rank <= :limit
ORDER BY units_rank, net_revenue DESC;
