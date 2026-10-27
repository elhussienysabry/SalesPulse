"""Registry and execution for the reusable SQL analytics layer.

All user-controlled filters are bound parameters. Query names come from a
controlled registry on disk; the application never executes arbitrary SQL from
the browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

from salespulse.config import ANALYTICS_SQL_DIR
from salespulse.exceptions import ReportError
from salespulse.transformations import CATEGORIES

_NAME_RE = re.compile(r"^--\s*name:\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*$", re.MULTILINE)
_DESCRIPTION_RE = re.compile(r"^--\s*description:\s*(.+)$", re.MULTILINE)
_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


@dataclass(frozen=True, slots=True)
class QuerySpec:
    name: str
    description: str
    sql: str
    source_file: str
    parameters: frozenset[str]

    def required_parameters(self) -> frozenset[str]:
        return self.parameters


@lru_cache(maxsize=1)
def load_query_catalog() -> dict[str, QuerySpec]:
    """Parse all ``-- name:`` sections from sql/analytics/*.sql."""
    catalog: dict[str, QuerySpec] = {}
    for path in sorted(Path(ANALYTICS_SQL_DIR).glob("*.sql")):
        content = path.read_text(encoding="utf-8")
        matches = list(_NAME_RE.finditer(content))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            if not block:
                raise ReportError(f"Empty SQL section {match.group(1)!r} in {path.name}")
            description_match = _DESCRIPTION_RE.search(block)
            description = description_match.group(1).strip() if description_match else ""
            # Remove the leading description comment from the executable SQL.
            sql = _DESCRIPTION_RE.sub("", block, count=1).strip()
            sql = sql.rstrip().removesuffix(";").strip()
            name = match.group(1)
            if name in catalog:
                raise ReportError(f"Duplicate SQL query name {name!r} in {path.name}")
            parameters = frozenset(_PARAM_RE.findall(sql))
            catalog[name] = QuerySpec(
                name=name,
                description=description,
                sql=sql,
                source_file=path.name,
                parameters=parameters,
            )
    if not catalog:
        raise ReportError(f"No analytics SQL files found in {ANALYTICS_SQL_DIR}")
    return catalog


def _parse_iso_date(value: str | date, field_name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ReportError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc


def validate_date_range(date_from: str | date, date_to: str | date) -> tuple[str, str]:
    start = _parse_iso_date(date_from, "date_from")
    end = _parse_iso_date(date_to, "date_to")
    if start > end:
        raise ReportError("date_from must be on or before date_to")
    return start, end


class AnalyticsService:
    """Execute known analytical queries against a SalesPulse database."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.catalog = load_query_catalog()

    def query_names(self) -> list[str]:
        return sorted(self.catalog)

    def describe(self, name: str) -> QuerySpec:
        try:
            return self.catalog[name]
        except KeyError as exc:
            raise ReportError(f"Unknown analytics query {name!r}") from exc

    def run_query(
        self,
        name: str,
        *,
        date_from: str | date | None = None,
        date_to: str | date | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> pd.DataFrame:
        spec = self.describe(name)
        parameters = spec.parameters
        values: dict[str, Any] = {}
        if {"date_from", "date_to"} & parameters:
            if date_from is None or date_to is None:
                raise ReportError(f"Query {name!r} requires a date range")
            start, end = validate_date_range(date_from, date_to)
            values.update({"date_from": start, "date_to": end})
        if "category" in parameters:
            if category is not None and category not in CATEGORIES:
                raise ReportError(f"Unknown category {category!r}")
            values["category"] = category
        if "limit" in parameters:
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
                raise ReportError("limit must be an integer between 1 and 1000")
            values["limit"] = limit
        missing = parameters - values.keys()
        if missing:
            raise ReportError(
                f"Query {name!r} is missing required parameters: {', '.join(sorted(missing))}"
            )
        try:
            with self.engine.connect() as conn:
                return pd.read_sql_query(text(spec.sql), conn, params=values)
        except Exception as exc:  # noqa: BLE001 - wrapped for consistent reporting
            raise ReportError(f"Failed to run analytics query {name!r}: {exc}") from exc

    # ------------------------------------------------------------------
    # Convenience wrappers grouped by dashboard section
    # ------------------------------------------------------------------

    def overview_metrics(self, date_from: str | date, date_to: str | date) -> pd.DataFrame:
        return self.run_query("overview_metrics", date_from=date_from, date_to=date_to)

    def order_status_breakdown(self, date_from: str | date, date_to: str | date) -> pd.DataFrame:
        return self.run_query("order_status_breakdown", date_from=date_from, date_to=date_to)

    def revenue_trends(self, date_from: str | date, date_to: str | date) -> dict[str, pd.DataFrame]:
        return {
            "daily": self.run_query("daily_revenue", date_from=date_from, date_to=date_to),
            "monthly": self.run_query("monthly_revenue", date_from=date_from, date_to=date_to),
            "monthly_mom": self.run_query(
                "monthly_revenue_mom", date_from=date_from, date_to=date_to
            ),
        }

    def product_performance(
        self,
        date_from: str | date,
        date_to: str | date,
        *,
        category: str | None = None,
    ) -> pd.DataFrame:
        return self.run_query(
            "product_performance",
            date_from=date_from,
            date_to=date_to,
            category=category,
        )

    def category_performance(
        self,
        date_from: str | date,
        date_to: str | date,
        *,
        category: str | None = None,
    ) -> pd.DataFrame:
        return self.run_query(
            "category_performance",
            date_from=date_from,
            date_to=date_to,
            category=category,
        )

    def top_products(
        self,
        date_from: str | date,
        date_to: str | date,
        *,
        by: str = "revenue",
        category: str | None = None,
        limit: int = 10,
    ) -> pd.DataFrame:
        name = "top_products_by_revenue" if by == "revenue" else "top_products_by_units"
        if by not in {"revenue", "units"}:
            raise ReportError("Products can be ranked by 'revenue' or 'units'")
        return self.run_query(
            name,
            date_from=date_from,
            date_to=date_to,
            category=category,
            limit=limit,
        )

    def customers(
        self, date_from: str | date, date_to: str | date, *, limit: int = 10
    ) -> dict[str, pd.DataFrame]:
        return {
            "new_vs_returning": self.run_query(
                "new_vs_returning", date_from=date_from, date_to=date_to
            ),
            "summary": self.run_query(
                "customer_purchase_summary", date_from=date_from, date_to=date_to
            ),
            "frequency": self.run_query(
                "customer_frequency_distribution", date_from=date_from, date_to=date_to
            ),
            "top": self.run_query(
                "top_customers", date_from=date_from, date_to=date_to, limit=limit
            ),
        }

    def regional_performance(self, date_from: str | date, date_to: str | date) -> pd.DataFrame:
        return self.run_query("regional_performance", date_from=date_from, date_to=date_to)

    def cancellation_and_return_rates(
        self, date_from: str | date, date_to: str | date
    ) -> pd.DataFrame:
        return self.run_query("cancellation_and_return_rates", date_from=date_from, date_to=date_to)

    def quality_checks(self) -> pd.DataFrame:
        return self.run_query("quality_checks")

    def date_filtered_orders(self, date_from: str | date, date_to: str | date) -> pd.DataFrame:
        return self.run_query("date_filtered_orders", date_from=date_from, date_to=date_to)

    def monthly_rankings(self, date_from: str | date, date_to: str | date) -> pd.DataFrame:
        return self.run_query("monthly_revenue_rank", date_from=date_from, date_to=date_to)

    def product_category_rankings(
        self,
        date_from: str | date,
        date_to: str | date,
        *,
        category: str | None = None,
    ) -> pd.DataFrame:
        return self.run_query(
            "product_category_rankings",
            date_from=date_from,
            date_to=date_to,
            category=category,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def date_bounds(self) -> tuple[str, str] | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT MIN(order_date), MAX(order_date) FROM orders")).one()
        if row[0] is None or row[1] is None:
            return None
        return str(row[0]), str(row[1])

    def available_categories(self) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT category FROM products ORDER BY category")
            ).all()
        return [str(row[0]) for row in rows]

    def revenue_range_total(self, date_from: str | date, date_to: str | date) -> float:
        frame = self.overview_metrics(date_from, date_to)
        if frame.empty:
            return 0.0
        value = frame.iloc[0]["net_revenue"]
        return float(value) if pd.notna(value) else 0.0


__all__ = [
    "AnalyticsService",
    "QuerySpec",
    "load_query_catalog",
    "validate_date_range",
]
