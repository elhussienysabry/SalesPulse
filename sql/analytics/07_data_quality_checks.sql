-- Data-quality and reconciliation checks.
-- Each row is one check. Zero failures means the check passes. Checks do not
-- modify data; issues are reported for human review.

-- name: quality_checks
-- description: SQL-based integrity, business-rule, and reconciliation checks.
WITH checks AS (
    SELECT
        'orphan_orders' AS check_name,
        'critical' AS severity,
        COUNT(*) AS failures,
        'Orders whose customer_id does not exist in customers.' AS detail
    FROM orders o
    LEFT JOIN customers c ON c.customer_id = o.customer_id
    WHERE c.customer_id IS NULL

    UNION ALL

    SELECT
        'orphan_order_items',
        'critical',
        COUNT(*),
        'Order items whose order or product does not exist.'
    FROM order_items oi
    LEFT JOIN orders o ON o.order_id = oi.order_id
    LEFT JOIN products p ON p.product_id = oi.product_id
    WHERE o.order_id IS NULL OR p.product_id IS NULL

    UNION ALL

    SELECT
        'orphan_returns',
        'critical',
        COUNT(*),
        'Returns whose order item does not exist.'
    FROM returns r
    LEFT JOIN order_items oi ON oi.order_item_id = r.order_item_id
    WHERE oi.order_item_id IS NULL

    UNION ALL

    SELECT
        'orphan_payments',
        'critical',
        COUNT(*),
        'Payments whose order does not exist.'
    FROM payments p
    LEFT JOIN orders o ON o.order_id = p.order_id
    WHERE o.order_id IS NULL

    UNION ALL

    SELECT
        'duplicate_primary_keys',
        'critical',
        COALESCE((SELECT SUM(n - 1) FROM (
            SELECT customer_id, COUNT(*) AS n FROM customers GROUP BY customer_id HAVING COUNT(*) > 1
        )), 0)
        + COALESCE((SELECT SUM(n - 1) FROM (
            SELECT product_id, COUNT(*) AS n FROM products GROUP BY product_id HAVING COUNT(*) > 1
        )), 0)
        + COALESCE((SELECT SUM(n - 1) FROM (
            SELECT order_id, COUNT(*) AS n FROM orders GROUP BY order_id HAVING COUNT(*) > 1
        )), 0)
        + COALESCE((SELECT SUM(n - 1) FROM (
            SELECT order_item_id, COUNT(*) AS n FROM order_items GROUP BY order_item_id HAVING COUNT(*) > 1
        )), 0)
        + COALESCE((SELECT SUM(n - 1) FROM (
            SELECT return_id, COUNT(*) AS n FROM returns GROUP BY return_id HAVING COUNT(*) > 1
        )), 0)
        + COALESCE((SELECT SUM(n - 1) FROM (
            SELECT payment_id, COUNT(*) AS n FROM payments GROUP BY payment_id HAVING COUNT(*) > 1
        )), 0),
        'Duplicate primary-key values across all business tables.'

    UNION ALL

    SELECT
        'duplicate_order_item_business_keys',
        'critical',
        COALESCE(SUM(n - 1), 0),
        'Repeated (order_id, product_id) pairs in order_items.'
    FROM (
        SELECT order_id, product_id, COUNT(*) AS n
        FROM order_items
        GROUP BY order_id, product_id
        HAVING COUNT(*) > 1
    ) x

    UNION ALL

    SELECT
        'missing_required_values',
        'critical',
        (SELECT COUNT(*) FROM customers
         WHERE trim(customer_id) = '' OR trim(first_name) = '' OR trim(email) = '')
        + (SELECT COUNT(*) FROM products
           WHERE trim(product_id) = '' OR trim(product_name) = '')
        + (SELECT COUNT(*) FROM orders
           WHERE trim(order_id) = '' OR trim(customer_id) = '')
        + (SELECT COUNT(*) FROM order_items
           WHERE trim(order_item_id) = '' OR trim(order_id) = '')
        + (SELECT COUNT(*) FROM returns
           WHERE trim(return_id) = '' OR trim(order_item_id) = ''),
        'Blank values in required business fields.'

    UNION ALL

    SELECT
        'invalid_statuses',
        'critical',
        (SELECT COUNT(*) FROM orders
         WHERE status NOT IN ('completed', 'pending', 'cancelled'))
        + (SELECT COUNT(*) FROM returns
           WHERE status NOT IN ('approved', 'requested', 'rejected'))
        + (SELECT COUNT(*) FROM payments
           WHERE status NOT IN ('paid', 'pending', 'failed')),
        'Status values outside the documented allow-lists.'

    UNION ALL

    SELECT
        'invalid_quantities_or_prices',
        'critical',
        (SELECT COUNT(*) FROM order_items
         WHERE quantity <= 0 OR unit_price <= 0
            OR discount_rate < 0 OR discount_rate > 0.90)
        + (SELECT COUNT(*) FROM returns
           WHERE quantity <= 0 OR refund_amount < 0),
        'Quantities, prices, discounts, or refunds outside valid ranges.'

    UNION ALL

    SELECT
        'orders_future_dated',
        'warning',
        COUNT(*),
        'Orders dated after the current date (clock or backfill issue).'
    FROM orders
    WHERE order_date > date('now')

    UNION ALL

    SELECT
        'date_sequence_errors',
        'critical',
        (SELECT COUNT(*) FROM returns r
         JOIN order_items oi ON oi.order_item_id = r.order_item_id
         JOIN orders o ON o.order_id = oi.order_id
         WHERE r.return_date < o.order_date)
        + (SELECT COUNT(*) FROM payments p
           JOIN orders o ON o.order_id = p.order_id
           WHERE p.paid_at IS NOT NULL AND p.paid_at < o.order_date)
        + (SELECT COUNT(*) FROM orders o
           JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.order_date < c.signup_date),
        'Returns, payments, or orders that precede their required predecessor date.'

    UNION ALL

    SELECT
        'returns_on_non_completed_orders',
        'critical',
        COUNT(*),
        'Returns attached to orders that are not completed.'
    FROM returns r
    JOIN order_items oi ON oi.order_item_id = r.order_item_id
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.status <> 'completed'

    UNION ALL

    SELECT
        'return_quantity_exceeds_purchase',
        'critical',
        COUNT(*),
        'Combined return quantities exceed the purchased quantity.'
    FROM (
        SELECT r.order_item_id
        FROM returns r
        JOIN order_items oi ON oi.order_item_id = r.order_item_id
        GROUP BY r.order_item_id, oi.quantity
        HAVING SUM(r.quantity) > oi.quantity
    )

    UNION ALL

    SELECT
        'approved_refunds_exceed_line_net',
        'critical',
        COUNT(*),
        'Approved refund totals exceed the discounted value of the order line.'
    FROM (
        SELECT r.order_item_id
        FROM returns r
        JOIN order_items oi ON oi.order_item_id = r.order_item_id
        WHERE r.status = 'approved'
        GROUP BY r.order_item_id, oi.quantity, oi.unit_price, oi.discount_rate
        HAVING SUM(r.refund_amount)
            > ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_rate) + 1e-9, 2) + 0.005
    )

    UNION ALL

    SELECT
        'payments_for_cancelled_orders',
        'critical',
        COUNT(*),
        'Payments recorded against cancelled orders.'
    FROM payments p
    JOIN orders o ON o.order_id = p.order_id
    WHERE o.status = 'cancelled'

    UNION ALL

    SELECT
        'payment_amount_mismatch',
        'critical',
        COUNT(*),
        'Payment amount differs from the order net sales by more than 0.01.'
    FROM payments p
    JOIN v_order_financials o ON o.order_id = p.order_id
    WHERE o.status IN ('completed', 'pending')
      AND ROUND(ABS(p.amount - o.net_sales), 2) > 0.01

    UNION ALL

    SELECT
        'completed_orders_without_items',
        'critical',
        COUNT(*),
        'Completed orders with no order lines (cannot contribute revenue).'
    FROM orders o
    WHERE o.status = 'completed'
      AND NOT EXISTS (
          SELECT 1 FROM order_items oi WHERE oi.order_id = o.order_id
      )

    UNION ALL

    SELECT
        'duplicate_order_events',
        'warning',
        COALESCE(SUM(n - 1), 0),
        'Possible duplicate order events: same customer, date, and item value.'
    FROM (
        SELECT o.customer_id, o.order_date, o.item_value, COUNT(*) AS n
        FROM (
            SELECT
                o.order_id,
                o.customer_id,
                o.order_date,
                ROUND(SUM(oi.quantity * oi.unit_price) + 1e-9, 2) AS item_value
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            GROUP BY o.order_id, o.customer_id, o.order_date
        ) o
        GROUP BY o.customer_id, o.order_date, o.item_value
        HAVING COUNT(*) > 1
    ) AS possible_duplicates

    UNION ALL

    SELECT
        'revenue_reconciliation_order_vs_line',
        'critical',
        CASE WHEN ABS(
            COALESCE((SELECT SUM(net_revenue) FROM v_order_financials), 0)
            - COALESCE((SELECT SUM(net_revenue) FROM v_order_line_financials), 0)
        ) > 0.01 THEN 1 ELSE 0 END,
        'Order-level net revenue must equal the sum of line-level net revenue.'

    UNION ALL

    SELECT
        'revenue_component_reconciliation',
        'critical',
        CASE WHEN ABS(
            COALESCE((SELECT SUM(net_sales) FROM v_order_financials
                      WHERE status = 'completed'), 0)
            - COALESCE((SELECT SUM(refunds) FROM v_order_financials
                        WHERE status = 'completed'), 0)
            - COALESCE((SELECT SUM(net_revenue) FROM v_order_financials
                        WHERE status = 'completed'), 0)
        ) > 0.01 THEN 1 ELSE 0 END,
        'Completed net sales minus approved refunds must equal net revenue.'

    UNION ALL

    SELECT
        'stuck_import_batches',
        'warning',
        COUNT(*),
        'Import batches left in processing for more than one hour.'
    FROM import_batches
    WHERE status = 'processing'
      AND datetime(started_at) < datetime('now', '-1 hour')
)
SELECT
    check_name,
    severity,
    failures,
    CASE WHEN failures = 0 THEN 'pass' ELSE 'fail' END AS status,
    detail
FROM checks
ORDER BY
    CASE severity WHEN 'critical' THEN 1 ELSE 2 END,
    check_name;
