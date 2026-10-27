-- Parameterised order-level report for a user-selected date range.

-- name: date_filtered_orders
-- description: Every order in the range, with status and financial measures.
SELECT
    o.order_id,
    o.order_date,
    o.customer_id,
    o.status,
    o.shipping_region,
    o.shipping_country,
    o.shipping_city,
    o.item_count,
    o.unit_count,
    ROUND(o.gross_sales, 2) AS gross_sales,
    ROUND(o.discount_amount, 2) AS discounts,
    ROUND(o.refunds, 2) AS refunds,
    ROUND(o.net_revenue, 2) AS net_revenue
FROM v_order_financials o
WHERE o.order_date BETWEEN :date_from AND :date_to
ORDER BY o.order_date, o.order_id;
