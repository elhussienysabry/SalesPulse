-- Customer acquisition, frequency, and spending.
-- A customer is "new" in the period when their first-ever completed order falls
-- inside the selected period, based on all available history in the database.

-- name: new_vs_returning
-- description: Customer count, orders, and revenue split by new vs returning.
WITH period_orders AS (
    SELECT
        o.customer_id,
        COUNT(*) AS orders,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue
    FROM v_order_financials o
    WHERE o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
    GROUP BY o.customer_id
),
first_orders AS (
    SELECT customer_id, MIN(order_date) AS first_order_date
    FROM v_order_financials
    WHERE status = 'completed'
    GROUP BY customer_id
)
SELECT
    CASE WHEN f.first_order_date >= :date_from THEN 'new' ELSE 'returning' END
        AS customer_type,
    COUNT(*) AS customers,
    SUM(p.orders) AS completed_orders,
    ROUND(SUM(p.net_revenue), 2) AS net_revenue,
    ROUND(SUM(p.net_revenue) / NULLIF(COUNT(*), 0), 2) AS revenue_per_customer
FROM period_orders p
JOIN first_orders f ON f.customer_id = p.customer_id
GROUP BY CASE WHEN f.first_order_date >= :date_from THEN 'new' ELSE 'returning' END
ORDER BY CASE customer_type WHEN 'new' THEN 1 ELSE 2 END;

-- name: customer_purchase_summary
-- description: One row per purchasing customer, with frequency and spending.
WITH period_orders AS (
    SELECT
        o.customer_id,
        COUNT(*) AS completed_orders,
        SUM(o.unit_count) AS units,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue,
        ROUND(SUM(o.net_revenue) / NULLIF(COUNT(*), 0), 2) AS average_order_value,
        MIN(o.order_date) AS first_purchase,
        MAX(o.order_date) AS last_purchase
    FROM v_order_financials o
    WHERE o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
    GROUP BY o.customer_id
),
first_orders AS (
    SELECT customer_id, MIN(order_date) AS first_order_date
    FROM v_order_financials
    WHERE status = 'completed'
    GROUP BY customer_id
)
SELECT
    c.customer_id,
    c.first_name || ' ' || c.last_name AS customer_name,
    c.region,
    CASE WHEN f.first_order_date >= :date_from THEN 'new' ELSE 'returning' END
        AS customer_type,
    p.completed_orders,
    p.units,
    p.net_revenue,
    p.average_order_value,
    p.first_purchase,
    p.last_purchase
FROM period_orders p
JOIN customers c ON c.customer_id = p.customer_id
JOIN first_orders f ON f.customer_id = p.customer_id
ORDER BY p.net_revenue DESC, c.customer_id;

-- name: customer_frequency_distribution
-- description: Customers grouped by completed-order count in the period.
WITH period_orders AS (
    SELECT
        o.customer_id,
        COUNT(*) AS completed_orders,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue
    FROM v_order_financials o
    WHERE o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
    GROUP BY o.customer_id
),
banded AS (
    SELECT
        customer_id,
        completed_orders,
        net_revenue,
        CASE
            WHEN completed_orders = 1 THEN '1 order'
            WHEN completed_orders BETWEEN 2 AND 3 THEN '2-3 orders'
            WHEN completed_orders BETWEEN 4 AND 6 THEN '4-6 orders'
            ELSE '7+ orders'
        END AS frequency_band
    FROM period_orders
)
SELECT
    frequency_band,
    COUNT(*) AS customers,
    SUM(completed_orders) AS completed_orders,
    ROUND(SUM(net_revenue), 2) AS net_revenue,
    ROUND(AVG(net_revenue), 2) AS average_customer_spend
FROM banded
GROUP BY frequency_band
ORDER BY CASE frequency_band
    WHEN '1 order' THEN 1
    WHEN '2-3 orders' THEN 2
    WHEN '4-6 orders' THEN 3
    ELSE 4
END;

-- name: top_customers
-- description: Top customers by net revenue with a dense-rank window.
WITH period_orders AS (
    SELECT
        o.customer_id,
        COUNT(*) AS completed_orders,
        ROUND(SUM(o.net_revenue), 2) AS net_revenue
    FROM v_order_financials o
    WHERE o.status = 'completed'
      AND o.order_date BETWEEN :date_from AND :date_to
    GROUP BY o.customer_id
),
ranked AS (
    SELECT
        c.customer_id,
        c.first_name || ' ' || c.last_name AS customer_name,
        c.region,
        p.completed_orders,
        p.net_revenue,
        DENSE_RANK() OVER (ORDER BY p.net_revenue DESC) AS spend_rank
    FROM period_orders p
    JOIN customers c ON c.customer_id = p.customer_id
)
SELECT *
FROM ranked
WHERE spend_rank <= :limit
ORDER BY spend_rank, customer_id;
