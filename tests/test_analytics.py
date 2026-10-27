"""SQL registry, date-filtering, and reconciliation tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from salespulse.analytics import AnalyticsService, load_query_catalog, validate_date_range
from salespulse.exceptions import ReportError

EXPECTED_QUERIES = {
    "daily_revenue",
    "monthly_revenue",
    "monthly_revenue_mom",
    "overview_metrics",
    "order_status_breakdown",
    "monthly_order_metrics",
    "product_performance",
    "category_performance",
    "top_products_by_revenue",
    "top_products_by_units",
    "new_vs_returning",
    "customer_purchase_summary",
    "customer_frequency_distribution",
    "top_customers",
    "regional_performance",
    "cancellation_and_return_rates",
    "quality_checks",
    "monthly_revenue_rank",
    "product_category_rankings",
    "date_filtered_orders",
}


def test_catalog_is_complete_and_documented() -> None:
    catalog = load_query_catalog()
    assert set(catalog) == EXPECTED_QUERIES
    for spec in catalog.values():
        assert spec.description, spec.name
        assert "-- name:" not in spec.sql
        assert not spec.sql.rstrip().endswith(";")


def test_all_queries_execute_for_full_range(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    for name, spec in service.catalog.items():
        frame = service.run_query(
            name,
            date_from=start,
            date_to=end,
            category=None,
            limit=5,
        )
        assert isinstance(frame, pd.DataFrame), name
        if "date_from" in spec.parameters:
            assert not frame.empty, name


def test_overview_matches_views_and_status_breakdown(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    overview = service.overview_metrics(start, end).iloc[0]
    status = service.order_status_breakdown(start, end)
    with clean_engine.connect() as conn:
        expected = (
            conn.execute(
                text(
                    """
                SELECT
                    COUNT(*) AS completed_orders,
                    COUNT(DISTINCT customer_id) AS customers,
                    SUM(net_revenue) AS net_revenue,
                    SUM(gross_sales) AS gross_sales,
                    SUM(discount_amount) AS discounts,
                    SUM(unit_count) AS units
                FROM v_order_financials
                WHERE status = 'completed'
                  AND order_date BETWEEN :start AND :end
                """
                ),
                {"start": start, "end": end},
            )
            .mappings()
            .one()
        )

    assert int(overview["completed_orders"]) == expected["completed_orders"]
    assert int(overview["unique_customers"]) == expected["customers"]
    assert float(overview["net_revenue"]) == pytest.approx(expected["net_revenue"], abs=0.01)
    assert float(overview["gross_sales"]) == pytest.approx(expected["gross_sales"], abs=0.01)
    assert float(overview["discounts"]) == pytest.approx(expected["discounts"], abs=0.01)
    assert int(overview["units_sold"]) == expected["units"]

    completed = status.loc[status["status"] == "completed"].iloc[0]
    assert float(completed["recognised_net_revenue"]) == pytest.approx(
        float(overview["net_revenue"]), abs=0.01
    )
    with clean_engine.connect() as conn:
        placed_orders = conn.execute(
            text("SELECT COUNT(*) FROM orders WHERE order_date BETWEEN :start AND :end"),
            {"start": start, "end": end},
        ).scalar_one()
    assert int(status["orders"].sum()) == placed_orders


def test_order_and_line_revenue_reconcile(clean_engine) -> None:
    with clean_engine.connect() as conn:
        order_total = conn.execute(
            text("SELECT COALESCE(SUM(net_revenue), 0) FROM v_order_financials")
        ).scalar_one()
        line_total = conn.execute(
            text("SELECT COALESCE(SUM(net_revenue), 0) FROM v_order_line_financials")
        ).scalar_one()
    assert float(order_total) == pytest.approx(float(line_total), abs=0.01)


def test_date_filter_is_inclusive_and_matches_raw_counts(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    first_day = start
    with clean_engine.connect() as conn:
        placed = conn.execute(
            text("SELECT COUNT(*) FROM orders WHERE order_date = :day"), {"day": first_day}
        ).scalar_one()
        completed = conn.execute(
            text("SELECT COUNT(*) FROM orders WHERE order_date = :day AND status = 'completed'"),
            {"day": first_day},
        ).scalar_one()

    filtered = service.date_filtered_orders(first_day, first_day)
    assert len(filtered) == placed
    overview = service.overview_metrics(first_day, first_day).iloc[0]
    assert int(overview["completed_orders"]) == completed

    # A range starting one day later must exclude the first day's orders.
    next_day = date.fromisoformat(first_day).toordinal() + 1
    next_day_text = date.fromordinal(next_day).isoformat()
    if next_day_text <= end:
        narrowed = service.date_filtered_orders(next_day_text, end)
        assert len(narrowed) == len(service.date_filtered_orders(start, end)) - placed


def test_limit_and_category_filters(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    categories = service.available_categories()
    assert categories
    top = service.top_products(start, end, category=categories[0], limit=3)
    assert len(top) <= 3
    if not top.empty:
        assert set(top["category"]) == {categories[0]}
        assert top["revenue_rank"].tolist() == list(range(1, len(top) + 1))

    products = service.product_performance(start, end, category=categories[0])
    assert set(products["category"]) == {categories[0]}


def test_parameter_validation_rejects_bad_input(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    start, end = service.date_bounds()
    with pytest.raises(ReportError, match="Unknown analytics query"):
        service.run_query("drop_everything")
    with pytest.raises(ReportError, match="requires a date range"):
        service.run_query("overview_metrics")
    with pytest.raises(ReportError, match="on or before"):
        validate_date_range("2026-01-02", "2026-01-01")
    with pytest.raises(ReportError, match="ISO date"):
        validate_date_range("not-a-date", "2026-01-01")
    with pytest.raises(ReportError, match="Unknown category"):
        service.run_query(
            "product_performance",
            date_from=start,
            date_to=end,
            category="Electronics'; DROP TABLE orders; --",
        )
    with pytest.raises(ReportError, match="limit"):
        service.run_query(
            "top_products_by_revenue",
            date_from=start,
            date_to=end,
            limit=0,
        )
    # The injection attempt must not have executed.
    with clean_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() > 0


def test_empty_range_returns_zero_metrics(clean_engine) -> None:
    service = AnalyticsService(clean_engine)
    overview = service.overview_metrics("2035-01-01", "2035-01-31").iloc[0]
    assert int(overview["completed_orders"]) == 0
    assert float(overview["net_revenue"]) == 0.0
    assert service.date_filtered_orders("2035-01-01", "2035-01-31").empty
