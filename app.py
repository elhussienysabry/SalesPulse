"""SalesPulse Streamlit dashboard.

Every metric and chart is computed from the SQLite database through the
documented SQL analytics layer. The demonstration data is synthetic.
"""

from __future__ import annotations

import html
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import Engine

from salespulse.analytics import AnalyticsService
from salespulse.config import PROJECT_ROOT, Settings
from salespulse.dashboard_data import (
    format_currency,
    format_number,
    format_pct,
    import_status_label,
    overview_cards,
    quality_cards,
    quality_failure_frame,
    spending_histogram,
    validated_date_range,
)
from salespulse.database import (
    create_db_engine,
    is_initialized,
    table_counts,
)
from salespulse.exceptions import SalesPulseError
from salespulse.exports import sanitize_frame
from salespulse.ingestion import (
    get_import_history,
    get_import_totals,
    get_last_import,
    get_rejection_report,
    ingest_file,
)
from salespulse.profiling import FileProfile, profile_frame, read_csv_bytes
from salespulse.quality import quality_summary, run_quality_checks
from salespulse.schema import EXPECTED_COLUMNS, INGESTION_ORDER

NAVY = "#0F2742"
TEAL = "#0F766E"
MINT = "#2DD4BF"
AMBER = "#D97706"
RED = "#B91C1C"
SLATE = "#64748B"
GRID = "#E7EDF3"
PALETTE = [TEAL, NAVY, AMBER, "#7C3AED", "#0369A1", "#DB2777"]

st.set_page_config(
    page_title="SalesPulse | Sales Analytics",
    page_icon="◔",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
:root {
  --sp-navy: #0F2742;
  --sp-teal: #0F766E;
  --sp-mint: #2DD4BF;
  --sp-slate: #64748B;
  --sp-border: #E4EAF1;
  --sp-bg: #F6F8FB;
}
html, body, [class*="css"] { font-family: Inter, "Segoe UI", system-ui, sans-serif; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--sp-border); }
[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] { visibility: hidden; }
.sp-brand { display: flex; align-items: center; gap: 12px; padding: 4px 0 18px 0; }
.sp-mark {
  width: 42px; height: 42px; border-radius: 12px; background: var(--sp-navy);
  color: #FFFFFF; display: flex; align-items: center; justify-content: center;
  font-weight: 800; letter-spacing: -.5px; font-size: 17px;
  box-shadow: 0 6px 18px rgba(15,39,66,.22);
}
.sp-brand-name { font-size: 21px; font-weight: 800; color: var(--sp-navy); line-height: 1.1; }
.sp-brand-tag { font-size: 10px; font-weight: 700; letter-spacing: .13em; color: var(--sp-teal); text-transform: uppercase; }
.sp-eyebrow { font-size: 11px; font-weight: 800; letter-spacing: .14em; color: var(--sp-teal); text-transform: uppercase; margin-bottom: 6px; }
h1.sp-title { font-size: 33px !important; line-height: 1.15 !important; color: var(--sp-navy); margin: 0 0 6px 0 !important; letter-spacing: -.03em; padding: 0 !important; }
p.sp-subtitle { color: #53657A; font-size: 14px; margin: 0 0 20px 0; max-width: 900px; }
.sp-pill { display: inline-flex; align-items: center; gap: 6px; background: #E7F7F4; color: #0B5E57; border: 1px solid #C7EEE8; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; margin-left: 8px; vertical-align: middle; }
.sp-pill.amber { background: #FFF7E6; color: #8A4B00; border-color: #FDE7B0; }
.sp-pill.red { background: #FDECEC; color: #991B1B; border-color: #F8CACA; }
.sp-kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(140px, 1fr)); gap: 12px; margin: 6px 0 22px 0; }
@media (max-width: 1200px) { .sp-kpi-grid { grid-template-columns: repeat(3, minmax(140px, 1fr)); } }
@media (max-width: 700px) { .sp-kpi-grid { grid-template-columns: repeat(2, minmax(140px, 1fr)); } }
.sp-kpi { background: #FFFFFF; border: 1px solid var(--sp-border); border-radius: 14px; padding: 15px 16px; box-shadow: 0 1px 2px rgba(15,39,66,.03); }
.sp-kpi-label { font-size: 10px; font-weight: 800; letter-spacing: .08em; color: var(--sp-slate); text-transform: uppercase; margin-bottom: 7px; }
.sp-kpi-value { font-size: 25px; font-weight: 800; color: var(--sp-navy); letter-spacing: -.035em; line-height: 1.1; }
.sp-kpi-help { font-size: 10px; color: #8091A5; margin-top: 6px; line-height: 1.35; }
.sp-section { margin: 8px 0 2px 0; }
.sp-section h3 { color: var(--sp-navy); font-size: 17px; letter-spacing: -.015em; margin-bottom: 2px; }
.sp-section p { color: #6B7C90; font-size: 12px; margin-top: 0; }
.sp-card { background: #FFFFFF; border: 1px solid var(--sp-border); border-radius: 14px; padding: 18px 20px; margin-bottom: 14px; }
.sp-empty { background: #FFFFFF; border: 1px dashed #C7D2DE; border-radius: 14px; padding: 34px; text-align: center; color: #64748B; margin: 10px 0 20px 0; }
.sp-empty strong { display: block; color: var(--sp-navy); font-size: 16px; margin-bottom: 6px; }
.sp-note { color: #6B7C90; font-size: 11px; line-height: 1.45; }
.sp-columns { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 10px 0; }
.sp-columns span { background: #F1F5F9; border: 1px solid #E2E8F0; color: #334E68; padding: 4px 8px; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.sp-divider { height: 1px; background: var(--sp-border); margin: 10px 0 18px 0; }
.sp-import-summary { background: #FFFFFF; border: 1px solid var(--sp-border); border-left: 4px solid var(--sp-teal); border-radius: 12px; padding: 16px 18px; margin: 8px 0 18px 0; }
.sp-import-summary.warn { border-left-color: var(--sp-amber); }
.sp-import-summary.fail { border-left-color: #B91C1C; }
.sp-import-summary h4 { margin: 0 0 4px 0; color: var(--sp-navy); font-size: 15px; }
.sp-import-summary p { margin: 0; color: #64748B; font-size: 12px; }
.sp-footer { color: #94A3B8; font-size: 10px; margin-top: 38px; border-top: 1px solid var(--sp-border); padding-top: 13px; }
[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid var(--sp-border); border-radius: 14px; padding: 12px 14px; }
.stButton button, .stDownloadButton button { border-radius: 9px; font-weight: 650; }
.stButton button[kind="primary"] { background: var(--sp-teal); border-color: var(--sp-teal); }
[data-testid="stFileUploader"] { background: #FFFFFF; border-radius: 12px; }
[data-testid="stDataFrame"] { border: 1px solid var(--sp-border); border-radius: 12px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

PLOT_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
}


@st.cache_resource(show_spinner=False)
def _cached_engine(path: str) -> Engine:
    return create_db_engine(path)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return path.name


def _render_brand() -> None:
    st.sidebar.markdown(
        """
        <div class="sp-brand">
          <div class="sp-mark">SP</div>
          <div>
            <div class="sp-brand-name">SalesPulse</div>
            <div class="sp-brand-tag">Sales intelligence</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _page_header(eyebrow: str, title: str, subtitle: str, *, pill: str = "Synthetic data") -> None:
    badge_class = "sp-pill amber" if pill.lower().startswith(("partial", "review")) else "sp-pill"
    st.markdown(
        f"""
        <div class="sp-eyebrow">{html.escape(eyebrow)}</div>
        <h1 class="sp-title">{html.escape(title)}
          <span class="{badge_class}">{html.escape(pill)}</span>
        </h1>
        <p class="sp-subtitle">{html.escape(subtitle)}</p>
        """,
        unsafe_allow_html=True,
    )


def _section(title: str, description: str = "") -> None:
    st.markdown(
        f"""
        <div class="sp-section">
          <h3>{html.escape(title)}</h3>
          {f"<p>{html.escape(description)}</p>" if description else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _empty_state(title: str, message: str) -> None:
    st.markdown(
        f"""
        <div class="sp-empty">
          <strong>{html.escape(title)}</strong>
          {html.escape(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_kpis(cards: list[dict[str, str]]) -> None:
    fragments = [
        '<div class="sp-kpi">'
        f'<div class="sp-kpi-label">{html.escape(card["label"])}</div>'
        f'<div class="sp-kpi-value">{html.escape(card["value"])}</div>'
        f'<div class="sp-kpi-help">{html.escape(card["help"])}</div>'
        "</div>"
        for card in cards
    ]
    st.markdown(f'<div class="sp-kpi-grid">{"".join(fragments)}</div>', unsafe_allow_html=True)


def _style_figure(fig: go.Figure, *, height: int = 330, show_legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=6, r=8, t=26, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color="#334E68", size=12),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=GRID),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
            visible=show_legend,
        ),
        showlegend=show_legend,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID, tickfont=dict(size=10))
    fig.update_yaxes(
        showgrid=True,
        gridcolor=GRID,
        zeroline=False,
        tickfont=dict(size=10),
        title_font=dict(size=11),
    )
    return fig


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return sanitize_frame(frame).to_csv(index=False, lineterminator="\n").encode("utf-8")


def _download_csv(
    frame: pd.DataFrame,
    filename: str,
    *,
    label: str = "Download CSV",
    key: str | None = None,
) -> None:
    if frame.empty:
        return
    st.download_button(
        label,
        data=_csv_bytes(frame),
        file_name=filename,
        mime="text/csv",
        key=key,
        width="content",
    )


def _render_setup_required(settings: Settings, *, reason: str = "") -> None:
    _render_brand()
    _page_header(
        "Setup required",
        "SalesPulse needs a database",
        "Initialize the SQLite database and load the deterministic demo data to continue.",
        pill="No database",
    )
    if reason:
        st.warning(reason)
    st.markdown(
        f"""
        <div class="sp-card">
          <div class="sp-note">
            Current database path: <code>{html.escape(_display_path(settings.db_path))}</code><br><br>
            Run these commands from the repository root:
          </div>
          <pre style="background:#0F2742;color:#E6F7F5;padding:16px;border-radius:10px;margin-top:12px;font-size:12px;line-height:1.7;">
python -m salespulse.cli demo --reset
streamlit run app.py</pre>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "The demo command generates fictional data from a fixed seed, initializes the schema, "
        "ingests valid records, runs data-quality checks, and writes CSV/Excel exports."
    )
    st.stop()


def _date_filter(bounds: tuple[str, str]) -> tuple[str, str, int]:
    min_date = date.fromisoformat(bounds[0])
    max_date = date.fromisoformat(bounds[1])
    default = (min_date, max_date)
    st.sidebar.markdown("#### Reporting period")
    selected = st.sidebar.date_input(
        "Date range",
        value=default,
        min_value=min_date,
        max_value=max_date,
        label_visibility="collapsed",
        key="global_date_range",
    )
    if isinstance(selected, tuple):
        if len(selected) != 2:
            st.sidebar.warning("Select both a start and end date.")
            st.stop()
        start, end = selected
    else:
        start = end = selected
    try:
        start_iso, end_iso = validated_date_range(
            start, end, data_min=bounds[0], data_max=bounds[1]
        )
    except SalesPulseError as exc:
        st.sidebar.error(str(exc))
        st.stop()
    days = (date.fromisoformat(end_iso) - date.fromisoformat(start_iso)).days + 1
    st.sidebar.caption(f"{days:,} days selected · all metrics use inclusive dates")
    return start_iso, end_iso, days


def _trend_figure(
    monthly: pd.DataFrame, daily: pd.DataFrame, days: int
) -> tuple[go.Figure, pd.DataFrame]:
    use_daily = days <= 75
    frame = daily if use_daily else monthly
    fig = go.Figure()
    if frame.empty:
        return _style_figure(fig), frame
    fig.add_trace(
        go.Bar(
            x=frame["period"],
            y=frame["gross_sales"],
            name="Gross sales",
            marker_color="#D9EEEA",
            hovertemplate="%{x}<br>Gross: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["period"],
            y=frame["net_revenue"],
            name="Net revenue",
            mode="lines+markers",
            line=dict(color=TEAL, width=3),
            marker=dict(size=5, color=TEAL),
            hovertemplate="%{x}<br>Net: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(barmode="group", hovermode="x unified")
    fig.update_yaxes(title_text="USD", tickprefix="$")
    _style_figure(fig, height=350)
    return fig, frame


def _status_donut(status_frame: pd.DataFrame) -> go.Figure:
    order = ["completed", "pending", "cancelled"]
    frame = status_frame.set_index("status").reindex(order).fillna(0).reset_index()
    colors = {"completed": TEAL, "pending": AMBER, "cancelled": RED}
    fig = go.Figure(
        go.Pie(
            labels=frame["status"].str.title(),
            values=frame["orders"],
            hole=0.62,
            marker=dict(colors=[colors.get(value, SLATE) for value in frame["status"]]),
            textinfo="label+percent",
            textfont=dict(size=11),
            hovertemplate="%{label}<br>%{value:,} orders<extra></extra>",
        )
    )
    total = int(frame["orders"].sum())
    fig.add_annotation(
        text=f"<b>{total:,}</b><br><span style='font-size:10px'>placed orders</span>",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=16, color=NAVY),
    )
    _style_figure(fig, height=285, show_legend=False)
    fig.update_layout(margin=dict(l=8, r=8, t=8, b=8))
    return fig


def _overview_page(engine: Engine, service: AnalyticsService, start: str, end: str) -> None:
    st.sidebar.markdown(
        '<div class="sp-note">Revenue-recognised metrics use completed orders only. '
        "Returns are attributed to the original order date.</div>",
        unsafe_allow_html=True,
    )
    _page_header(
        "Executive overview",
        "Revenue at a glance",
        "Completed-order performance for the selected period, calculated from the SalesPulse database.",
    )
    try:
        overview = service.overview_metrics(start, end)
        rates = service.cancellation_and_return_rates(start, end)
        status = service.order_status_breakdown(start, end)
        monthly = service.run_query("monthly_revenue", date_from=start, date_to=end)
        daily = service.run_query("daily_revenue", date_from=start, date_to=end)
        mom = service.run_query("monthly_revenue_mom", date_from=start, date_to=end)
    except SalesPulseError as exc:
        st.error(str(exc))
        st.stop()

    _render_kpis(overview_cards(overview, rates))
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    fig, trend_frame = _trend_figure(monthly, daily, days)
    left, right = st.columns([2.25, 1])
    with left:
        _section(
            "Revenue trend",
            f"{'Daily' if days <= 75 else 'Monthly'} view · gross sales bars and net revenue line",
        )
        if overview.empty or int(overview.iloc[0]["completed_orders"]) == 0:
            _empty_state(
                "No completed orders in this period",
                "Adjust the reporting period in the sidebar. The database still contains "
                "other historical orders and import records.",
            )
        else:
            st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
            _download_csv(
                trend_frame,
                f"revenue_trend_{start}_{end}.csv",
                label="Download trend data",
                key="overview_trend_download",
            )
    with right:
        _section("Order status", "All orders in the period, before revenue recognition")
        if status.empty:
            _empty_state("No placed orders", "No orders match the selected period.")
        else:
            st.plotly_chart(_status_donut(status), width="stretch", config=PLOT_CONFIG)

    _section("Monthly performance", "AOV uses net revenue divided by completed orders.")
    if monthly.empty:
        _empty_state("No monthly revenue", "No completed orders are available for these months.")
    else:
        display = monthly.copy()
        display.columns = [
            "Period",
            "Completed orders",
            "Gross sales",
            "Discounts",
            "Refunds",
            "Net revenue",
            "AOV",
        ]
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "Completed orders": st.column_config.NumberColumn(format="%d"),
                "Gross sales": st.column_config.NumberColumn(format="$%.2f"),
                "Discounts": st.column_config.NumberColumn(format="$%.2f"),
                "Refunds": st.column_config.NumberColumn(format="$%.2f"),
                "Net revenue": st.column_config.NumberColumn(format="$%.2f"),
                "AOV": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        _download_csv(
            monthly, f"monthly_revenue_{start}_{end}.csv", key="overview_monthly_download"
        )

    if not mom.empty and len(mom) > 1:
        _section(
            "Month-over-month revenue",
            "Change versus the previous month inside the selected period.",
        )
        chart = go.Figure()
        chart.add_trace(
            go.Bar(
                x=mom["period"],
                y=mom["mom_growth_pct"],
                marker_color=[
                    TEAL if value is not None and not pd.isna(value) and value >= 0 else RED
                    for value in mom["mom_growth_pct"]
                ],
                hovertemplate="%{x}<br>MoM: %{y:.2f}%<extra></extra>",
            )
        )
        chart.update_yaxes(title_text="Change %", ticksuffix="%")
        _style_figure(chart, height=250, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)

    st.markdown(
        '<div class="sp-footer">Synthetic demonstration data · '
        f"Source: {html.escape(_display_path(settings_db_path()))} · "
        f"Refreshed at query time {datetime.now().strftime('%H:%M:%S')}</div>",
        unsafe_allow_html=True,
    )


def settings_db_path() -> Path:
    return Settings.from_env().db_path


def _product_page(engine: Engine, service: AnalyticsService, start: str, end: str) -> None:
    st.sidebar.markdown("#### Product filters")
    categories = ["All categories"] + service.available_categories()
    category_choice = st.sidebar.selectbox(
        "Category",
        categories,
        index=0,
        key="product_category_filter",
    )
    category = None if category_choice == "All categories" else category_choice
    st.sidebar.markdown(
        '<div class="sp-note">Filters below the date range apply to product and category '
        "views. Returns reduce net revenue.</div>",
        unsafe_allow_html=True,
    )
    _page_header(
        "Product performance",
        "What is selling, and what is coming back",
        "Revenue is net of discounts and approved refunds on completed orders. "
        "Units sold are gross units before returns.",
    )
    try:
        products = service.product_performance(start, end, category=category)
        category_frame = service.category_performance(start, end, category=category)
        top = service.top_products(start, end, by="revenue", category=category, limit=10)
    except SalesPulseError as exc:
        st.error(str(exc))
        st.stop()

    if products.empty:
        _empty_state(
            "No product sales in this period",
            "Try a wider date range or a different category. "
            "No values are fabricated for empty filters.",
        )
        return
    total_revenue = float(products["net_revenue"].sum())
    total_units = int(products["units_sold"].sum())
    returned_units = int(products["returned_units"].sum())
    return_rate = 100.0 * returned_units / total_units if total_units else 0.0
    _render_kpis(
        [
            {
                "label": "Product net revenue",
                "value": format_currency(total_revenue),
                "help": "Sum of product-level net revenue",
            },
            {
                "label": "Units sold",
                "value": format_number(total_units),
                "help": "Gross units before approved returns",
            },
            {
                "label": "Returned units",
                "value": format_number(returned_units),
                "help": "Approved returned units",
            },
            {
                "label": "Product return rate",
                "value": format_pct(return_rate),
                "help": "Returned units ÷ units sold",
            },
            {
                "label": "Products sold",
                "value": format_number(len(products)),
                "help": f"Category filter: {category_choice}",
            },
        ]
    )

    left, right = st.columns([1.25, 1])
    with left:
        _section("Top products by net revenue", "Top 10 in the selected period and category")
        chart = go.Figure(
            go.Bar(
                x=top["net_revenue"],
                y=top["product_name"],
                orientation="h",
                marker_color=TEAL,
                customdata=top[["units_sold"]].to_numpy(),
                hovertemplate="%{y}<br>Net: $%{x:,.2f}<br>Units: %{customdata[0]:,}<extra></extra>",
            )
        )
        chart.update_yaxes(autorange="reversed", title_text="")
        chart.update_xaxes(title_text="Net revenue (USD)", tickprefix="$")
        _style_figure(chart, height=360, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)
    with right:
        _section("Revenue by category", "Net revenue after discounts and refunds")
        chart = go.Figure(
            go.Bar(
                x=category_frame["category"],
                y=category_frame["net_revenue"],
                marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(category_frame))],
                hovertemplate="%{x}<br>$%{y:,.2f}<extra></extra>",
            )
        )
        chart.update_xaxes(tickangle=-25)
        chart.update_yaxes(title_text="Net revenue", tickprefix="$")
        _style_figure(chart, height=360, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)

    _section(
        "Product performance table",
        "One row per product. Revenue per unit uses net revenue after approved refunds.",
    )
    display = products.rename(
        columns={
            "product_id": "Product ID",
            "product_name": "Product",
            "category": "Category",
            "orders": "Orders",
            "units_sold": "Units sold",
            "returned_units": "Returned units",
            "gross_sales": "Gross sales",
            "discounts": "Discounts",
            "refunds": "Refunds",
            "net_revenue": "Net revenue",
            "revenue_per_unit": "Revenue / unit",
            "unit_retention_pct": "Unit retention %",
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Orders": st.column_config.NumberColumn(format="%d"),
            "Units sold": st.column_config.NumberColumn(format="%d"),
            "Returned units": st.column_config.NumberColumn(format="%d"),
            "Gross sales": st.column_config.NumberColumn(format="$%.2f"),
            "Discounts": st.column_config.NumberColumn(format="$%.2f"),
            "Refunds": st.column_config.NumberColumn(format="$%.2f"),
            "Net revenue": st.column_config.NumberColumn(format="$%.2f"),
            "Revenue / unit": st.column_config.NumberColumn(format="$%.2f"),
            "Unit retention %": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    _download_csv(
        products,
        f"product_performance_{start}_{end}.csv",
        label="Download product table",
        key="product_table_download",
    )
    st.markdown(
        '<div class="sp-footer">Synthetic data · '
        "Revenue definition: gross line value − line discount − approved refunds.</div>",
        unsafe_allow_html=True,
    )


def _customer_page(engine: Engine, service: AnalyticsService, start: str, end: str) -> None:
    st.sidebar.markdown(
        '<div class="sp-note">“New” means the customer’s first-ever completed order '
        "falls inside the selected period.</div>",
        unsafe_allow_html=True,
    )
    _page_header(
        "Customer analytics",
        "Who buys, how often, and how much",
        "Purchase behaviour uses completed orders and net revenue in the selected period.",
    )
    try:
        data = service.customers(start, end, limit=10)
    except SalesPulseError as exc:
        st.error(str(exc))
        st.stop()
    summary = data["summary"]
    new_vs = data["new_vs_returning"]
    frequency = data["frequency"]
    top = data["top"]
    if summary.empty:
        _empty_state(
            "No customer purchases in this period",
            "No completed orders belong to the current date range. "
            "Adjust the period to explore historical customers.",
        )
        return

    new_count = (
        int(new_vs.loc[new_vs["customer_type"] == "new", "customers"].sum())
        if not new_vs.empty
        else 0
    )
    return_count = (
        int(new_vs.loc[new_vs["customer_type"] == "returning", "customers"].sum())
        if not new_vs.empty
        else 0
    )
    repeat_share = 100.0 * return_count / max(return_count + new_count, 1)
    avg_spend = float(summary["net_revenue"].mean())
    _render_kpis(
        [
            {
                "label": "Purchasing customers",
                "value": format_number(len(summary)),
                "help": "Distinct customers with at least one completed order",
            },
            {
                "label": "New customers",
                "value": format_number(new_count),
                "help": "First-ever completed order within this period",
            },
            {
                "label": "Returning customers",
                "value": format_number(return_count),
                "help": f"{repeat_share:.1f}% of purchasing customers",
            },
            {
                "label": "Average customer spend",
                "value": format_currency(avg_spend),
                "help": "Mean net revenue per purchasing customer",
            },
            {
                "label": "Top customer spend",
                "value": format_currency(summary["net_revenue"].max()),
                "help": "Largest customer net revenue in period",
            },
        ]
    )

    left, right = st.columns([1, 1.25])
    with left:
        _section("New vs returning", "Customers by acquisition status")
        chart = go.Figure(
            go.Pie(
                labels=new_vs["customer_type"].str.title(),
                values=new_vs["customers"],
                hole=0.62,
                marker=dict(colors=[AMBER, TEAL]),
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,} customers<extra></extra>",
            )
        )
        chart.add_annotation(
            text=f"<b>{new_count + return_count:,}</b><br><span style='font-size:10px'>customers</span>",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color=NAVY),
        )
        _style_figure(chart, height=300, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)
        if return_count == 0 and new_count:
            st.caption(
                "The full history is selected, so every purchasing customer's first-ever "
                "completed order falls inside this period."
            )
    with right:
        _section("Customer spending distribution", "Number of customers by net-revenue band")
        histogram = spending_histogram(summary)
        chart = go.Figure(
            go.Bar(
                x=histogram["spend_band"],
                y=histogram["customers"],
                marker_color=MINT,
                hovertemplate="%{x}<br>%{y:,} customers<extra></extra>",
            )
        )
        chart.update_yaxes(title_text="Customers")
        _style_figure(chart, height=300, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)

    left, right = st.columns([1, 1.35])
    with left:
        _section("Purchase frequency", "Distribution of completed-order counts")
        display = frequency.rename(
            columns={
                "frequency_band": "Orders per customer",
                "customers": "Customers",
                "completed_orders": "Completed orders",
                "net_revenue": "Net revenue",
                "average_customer_spend": "Average spend",
            }
        )
        chart = go.Figure(
            go.Bar(
                x=display["Orders per customer"],
                y=display["Customers"],
                marker_color=PALETTE[: len(display)],
                hovertemplate="%{x}<br>%{y:,} customers<extra></extra>",
            )
        )
        chart.update_yaxes(title_text="Customers")
        _style_figure(chart, height=280, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)
    with right:
        _section("Top customers by net revenue", "May include multiple completed orders")
        top_display = top.rename(
            columns={
                "customer_id": "Customer ID",
                "customer_name": "Customer",
                "region": "Region",
                "completed_orders": "Orders",
                "net_revenue": "Net revenue",
                "spend_rank": "Rank",
            }
        )
        st.dataframe(
            top_display,
            hide_index=True,
            width="stretch",
            column_config={
                "Orders": st.column_config.NumberColumn(format="%d"),
                "Net revenue": st.column_config.NumberColumn(format="$%.2f"),
                "Rank": st.column_config.NumberColumn(format="%d"),
            },
        )

    _section(
        "Customer purchase summary",
        "All purchasing customers in the period. Download includes full precision.",
    )
    display = summary.rename(
        columns={
            "customer_id": "Customer ID",
            "customer_name": "Customer",
            "region": "Region",
            "customer_type": "Type",
            "completed_orders": "Orders",
            "units": "Units",
            "net_revenue": "Net revenue",
            "average_order_value": "AOV",
            "first_purchase": "First purchase",
            "last_purchase": "Last purchase",
        }
    )
    display["Type"] = display["Type"].str.title()
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Orders": st.column_config.NumberColumn(format="%d"),
            "Units": st.column_config.NumberColumn(format="%d"),
            "Net revenue": st.column_config.NumberColumn(format="$%.2f"),
            "AOV": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    _download_csv(
        summary,
        f"customer_summary_{start}_{end}.csv",
        label="Download customer table",
        key="customer_table_download",
    )
    st.markdown(
        '<div class="sp-footer">Synthetic data · Customer counts are distinct purchasers, '
        "not order counts.</div>",
        unsafe_allow_html=True,
    )


def _regional_page(engine: Engine, service: AnalyticsService, start: str, end: str) -> None:
    st.sidebar.markdown(
        '<div class="sp-note">Region is the order’s shipping region. Customers are counted '
        "only when an order in the period is completed.</div>",
        unsafe_allow_html=True,
    )
    _page_header(
        "Geographic analysis",
        "Where orders and revenue come from",
        "Regional shipping performance for the selected period. Cancellation rates use all "
        "placed orders; revenue uses completed orders.",
    )
    try:
        regional = service.regional_performance(start, end)
    except SalesPulseError as exc:
        st.error(str(exc))
        st.stop()
    if regional.empty:
        _empty_state(
            "No regional activity in this period",
            "No placed orders match the current date range.",
        )
        return
    _render_kpis(
        [
            {
                "label": "Regions active",
                "value": format_number((regional["all_orders"] > 0).sum()),
                "help": "Regions with at least one placed order",
            },
            {
                "label": "Completed orders",
                "value": format_number(regional["completed_orders"].sum()),
                "help": "Orders that recognise revenue",
            },
            {
                "label": "Net revenue",
                "value": format_currency(regional["net_revenue"].sum()),
                "help": "Sum across shipping regions",
            },
            {
                "label": "Top region",
                "value": str(regional.iloc[0]["shipping_region"]).split()[0],
                "help": f"Ranked by net revenue: {format_currency(regional.iloc[0]['net_revenue'])}",
            },
        ]
    )

    left, right = st.columns([1.55, 1])
    with left:
        _section("Net revenue by region", "Completed orders only")
        chart = go.Figure(
            go.Bar(
                x=regional["shipping_region"],
                y=regional["net_revenue"],
                marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(regional))],
                customdata=regional[["all_orders", "cancellation_rate_pct"]].to_numpy(),
                hovertemplate=(
                    "%{x}<br>Net revenue: $%{y:,.2f}<br>"
                    "All orders: %{customdata[0]:,}<br>"
                    "Cancellation: %{customdata[1]:.2f}%<extra></extra>"
                ),
            )
        )
        chart.update_yaxes(title_text="Net revenue", tickprefix="$")
        _style_figure(chart, height=350, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)
    with right:
        _section("Order volume vs revenue", "Bubble size is net revenue")
        chart = go.Figure(
            go.Scatter(
                x=regional["all_orders"],
                y=regional["net_revenue"],
                mode="markers+text",
                text=regional["shipping_region"],
                textposition=[
                    "bottom center" if rank == 2 else "top center"
                    for rank in regional["revenue_rank"]
                ],
                textfont=dict(size=10),
                cliponaxis=False,
                marker=dict(
                    size=(
                        regional["net_revenue"].astype(float)
                        / max(regional["net_revenue"].max(), 1)
                        * 38
                        + 12
                    ),
                    color=PALETTE[: len(regional)],
                    line=dict(color="white", width=2),
                ),
                hovertemplate="%{text}<br>Orders: %{x}<br>Revenue: $%{y:,.2f}<extra></extra>",
            )
        )
        chart.update_xaxes(title_text="All placed orders")
        chart.update_yaxes(title_text="Net revenue", tickprefix="$")
        _style_figure(chart, height=350, show_legend=False)
        st.plotly_chart(chart, width="stretch", config=PLOT_CONFIG)

    _section("Regional performance table", "Revenue, AOV, and cancellation rate by region")
    display = regional.rename(
        columns={
            "shipping_region": "Region",
            "all_orders": "All orders",
            "completed_orders": "Completed",
            "cancelled_orders": "Cancelled",
            "unique_customers": "Customers",
            "gross_sales": "Gross sales",
            "discounts": "Discounts",
            "refunds": "Refunds",
            "net_revenue": "Net revenue",
            "average_order_value": "AOV",
            "cancellation_rate_pct": "Cancellation %",
            "revenue_share_pct": "Revenue share %",
            "revenue_rank": "Rank",
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "All orders": st.column_config.NumberColumn(format="%d"),
            "Completed": st.column_config.NumberColumn(format="%d"),
            "Cancelled": st.column_config.NumberColumn(format="%d"),
            "Customers": st.column_config.NumberColumn(format="%d"),
            "Gross sales": st.column_config.NumberColumn(format="$%.2f"),
            "Discounts": st.column_config.NumberColumn(format="$%.2f"),
            "Refunds": st.column_config.NumberColumn(format="$%.2f"),
            "Net revenue": st.column_config.NumberColumn(format="$%.2f"),
            "AOV": st.column_config.NumberColumn(format="$%.2f"),
            "Cancellation %": st.column_config.NumberColumn(format="%.2f"),
            "Revenue share %": st.column_config.NumberColumn(format="%.2f"),
            "Rank": st.column_config.NumberColumn(format="%d"),
        },
    )
    _download_csv(
        regional,
        f"regional_performance_{start}_{end}.csv",
        label="Download regional table",
        key="regional_table_download",
    )
    st.markdown(
        '<div class="sp-footer">Synthetic data · Region labels come from order shipping '
        "records, not from customer profil.</div>",
        unsafe_allow_html=True,
    )


def _import_summary_frame(summary: dict[str, Any]) -> pd.DataFrame:
    rows = summary.get("rejections", [])
    if not rows:
        return pd.DataFrame(columns=["row_number", "dataset", "reasons", "raw_data"])
    return pd.DataFrame(rows)[["row_number", "dataset", "reasons", "raw_data"]]


def _render_import_audit(summary: dict[str, Any]) -> None:
    status = summary["status"]
    css = "warn" if status == "partial" else ""
    st.markdown(
        f"""
        <div class="sp-import-summary {css}">
          <h4>Import {import_status_label(status)} — {html.escape(str(summary["dataset"]))}</h4>
          <p>{html.escape(str(summary["source_file"]))} · {html.escape(str(summary["started_at"]))} ·
          {int(summary["total_rows"]):,} rows read · {int(summary["valid_rows"]):,} accepted ·
          {int(summary["rejected_rows"]):,} rejected</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Inserted", f"{int(summary['inserted_rows']):,}")
    cols[1].metric("Updated", f"{int(summary['updated_rows']):,}")
    cols[2].metric("Unchanged", f"{int(summary['unchanged_rows']):,}")
    cols[3].metric("Rejected", f"{int(summary['rejected_rows']):,}")
    rejections = _import_summary_frame(summary)
    if not rejections.empty:
        st.dataframe(rejections, hide_index=True, width="stretch")
        st.download_button(
            "Download rejection report",
            data=_csv_bytes(rejections),
            file_name=f"rejections_{summary['import_id']}.csv",
            mime="text/csv",
            key=f"audit_rejections_{summary['import_id']}",
        )
    st.download_button(
        "Download import summary (JSON)",
        data=json.dumps(summary, indent=2, sort_keys=True, default=str).encode("utf-8"),
        file_name=f"import_summary_{summary['import_id']}.json",
        mime="application/json",
        key=f"audit_json_{summary['import_id']}",
    )


def _profile_display(profile: FileProfile) -> None:
    _render_kpis(
        [
            {
                "label": "Rows read",
                "value": f"{profile.summary['rows']:,}",
                "help": "Raw data rows",
            },
            {"label": "Columns", "value": f"{profile.summary['columns']:,}", "help": "Raw fields"},
            {
                "label": "Missing cells",
                "value": f"{profile.summary['missing_cells']:,}",
                "help": "Blank or null values before validation",
            },
            {
                "label": "Duplicate rows",
                "value": f"{profile.summary['duplicate_rows']:,}",
                "help": "Rows with an identical duplicate anywhere in the file",
            },
        ]
    )
    _section(
        "Data-quality profile",
        "Inferred types and missingness are shown before any business validation is applied.",
    )
    column_display = profile.columns.rename(
        columns={
            "column": "Column",
            "inferred_type": "Inferred type",
            "non_null": "Non-null",
            "missing": "Missing",
            "missing_pct": "Missing %",
            "unique_values": "Unique",
            "example": "Example",
        }
    )
    st.dataframe(
        column_display,
        hide_index=True,
        width="stretch",
        column_config={
            "Non-null": st.column_config.NumberColumn(format="%d"),
            "Missing": st.column_config.NumberColumn(format="%d"),
            "Missing %": st.column_config.NumberColumn(format="%.2f"),
            "Unique": st.column_config.NumberColumn(format="%d"),
        },
    )
    with st.expander("Expected schema"):
        st.write(", ".join(EXPECTED_COLUMNS[profile.summary["dataset"]]))
        st.caption(
            "Required columns are validated exactly. Known categorical aliases can be "
            "normalized using the import setting."
        )


def _dry_run_comparison(profile: FileProfile, summary: dict[str, Any]) -> None:
    valid = int(summary["valid_rows"])
    rejected = int(summary["rejected_rows"])
    _section(
        "Before / after validation",
        "Source quality vs the rows that will be written to SQLite. A dry run is rolled back.",
    )
    before, arrow, after = st.columns([1, 0.15, 1])
    with before:
        st.markdown("**Source file**")
        st.metric("Rows read", f"{profile.summary['rows']:,}")
        st.metric("Missing cells", f"{profile.summary['missing_cells']:,}")
        st.metric("Duplicate rows", f"{profile.summary['duplicate_rows']:,}")
    with arrow:
        st.markdown(
            "<div style='text-align:center;font-size:30px;color:#94A3B8;padding-top:50px;'>→</div>",
            unsafe_allow_html=True,
        )
    with after:
        st.markdown("**Validated batch**")
        st.metric("Rows accepted", f"{valid:,}")
        st.metric(
            "Rows rejected",
            f"{rejected:,}",
            delta=f"{rejected} excluded" if rejected else "0 excluded",
            delta_color="inverse",
        )
        st.metric("Writes now", "0 (dry run)")
    if rejected:
        st.warning(
            f"{rejected} row(s) would be rejected. Valid rows can still be imported; "
            "rejections are stored with reasons and never silently dropped."
        )
        rejections = _import_summary_frame(summary)
        st.dataframe(rejections, hide_index=True, width="stretch")
        _download_csv(
            rejections,
            f"dry_run_rejections_{summary['dataset']}.csv",
            label="Download rejection report",
            key="dry_run_rejections_download",
        )
    else:
        st.success("All rows pass static and business validation. Nothing would be rejected.")


def _upload_tab(engine: Engine, settings: Settings) -> None:
    audit = st.session_state.pop("last_import_audit", None)
    if audit:
        _section(
            "Last import audit",
            "This batch is committed. Re-importing the same file is idempotent.",
        )
        _render_import_audit(audit)

    _section(
        "Load new source data",
        "CSV only · maximum 25 MB · data is not written until you choose Import valid rows.",
    )
    config_col, upload_col = st.columns([1, 2.15])
    with config_col:
        st.markdown("#### Import configuration")
        dataset = st.selectbox(
            "Dataset",
            INGESTION_ORDER,
            index=INGESTION_ORDER.index("orders"),
            key="upload_dataset",
            help="Choose the dataset that matches the file columns.",
        )
        normalize_labels = st.checkbox(
            "Normalize documented label variants",
            value=True,
            help=(
                "Maps values such as 'Complete' to 'completed' and 'home and kitchen' "
                "to 'Home & Kitchen'. Unknown values are still rejected."
            ),
        )
        st.caption("Dry runs execute the full transaction and roll it back. No rows are written.")
        expected = EXPECTED_COLUMNS[dataset]
        st.markdown("**Expected columns**")
        chips = "".join(f"<span>{html.escape(column)}</span>" for column in expected)
        st.markdown(f'<div class="sp-columns">{chips}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sp-note">Categorical aliases are documented in '
            "<code>docs/data_quality_rules.md</code>. Corrections are never applied silently.</div>",
            unsafe_allow_html=True,
        )
    with upload_col:
        uploaded = st.file_uploader(
            "Upload a CSV file",
            type=["csv"],
            key="source_upload",
            help="Use the clean or messy sample files under data/raw/.",
        )
        if uploaded is None:
            _empty_state(
                "No file selected",
                "Upload customers.csv, products.csv, orders.csv, order_items.csv, returns.csv, "
                "or payments.csv. Try data/raw/messy/orders.csv to see rejection handling.",
            )
            return
        try:
            data = uploaded.getvalue()
            raw_frame = read_csv_bytes(data, filename=uploaded.name)
            profile = profile_frame(raw_frame, dataset)
        except SalesPulseError as exc:
            st.error(str(exc))
            return
        st.caption(
            f"{uploaded.name} · {len(data) / 1024:.1f} KB · {profile.summary['rows']:,} rows"
        )
        if profile.missing_columns or profile.unexpected_columns:
            problems = []
            if profile.missing_columns:
                problems.append("missing: " + ", ".join(profile.missing_columns))
            if profile.unexpected_columns:
                problems.append("unexpected: " + ", ".join(profile.unexpected_columns))
            st.error("Schema mismatch — " + "; ".join(problems))
        else:
            st.success("Schema matches the expected columns.")
        st.markdown("#### File preview")
        st.dataframe(raw_frame.head(50), hide_index=True, width="stretch")
        st.caption("Showing the first 50 raw rows exactly as read from the CSV.")

        _profile_display(profile)

        _section("Run validation", "Static schema checks and database-backed business rules.")
        button_col, import_col = st.columns(2)
        schema_ok = not profile.missing_columns and not profile.unexpected_columns
        dry_run_clicked = button_col.button(
            "Validate file (dry run)",
            type="secondary",
            width="stretch",
            disabled=not schema_ok,
            key="dry_run_button",
        )
        import_clicked = import_col.button(
            "Import valid rows",
            type="primary",
            width="stretch",
            disabled=not schema_ok,
            key="import_button",
        )
        if dry_run_clicked or import_clicked:
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "wb", suffix=".csv", prefix="salespulse_upload_", delete=False
                ) as handle:
                    handle.write(data)
                    temp_path = Path(handle.name)
                with st.spinner("Running schema, business-rule, and database checks..."):
                    summary = ingest_file(
                        engine,
                        temp_path,
                        dataset,
                        normalize_labels=normalize_labels,
                        as_of_date=settings.as_of_date,
                        dry_run=dry_run_clicked,
                    )
                payload = summary.to_dict()
                if dry_run_clicked:
                    st.session_state["last_dry_run"] = payload
                    st.success("Dry run complete — the transaction was rolled back.")
                    _dry_run_comparison(profile, payload)
                else:
                    st.session_state["last_import_audit"] = payload
                    st.rerun()
            except SalesPulseError as exc:
                st.error(str(exc))
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

    stored_preview = st.session_state.get("last_dry_run")
    if stored_preview and stored_preview.get("source_file") == uploaded.name:
        _dry_run_comparison(profile, stored_preview)


def _history_tab(engine: Engine) -> None:
    history = get_import_history(engine)
    totals = get_import_totals(engine)
    _section(
        "Import history",
        "Every validation run that reached the database is recorded. Failed batches are rolled back.",
    )
    cols = st.columns(4)
    cols[0].metric("Committed batches", f"{totals['batches']:,}")
    cols[1].metric("Processed rows", f"{totals['processed_rows']:,}")
    cols[2].metric("Rejected rows", f"{totals['rejected_rows']:,}")
    last = get_last_import(engine)
    cols[3].metric(
        "Latest batch",
        str(last["started_at"])[:10] if last else "—",
        help=(
            f"{str(last['status']).title()} · {last['started_at']} (UTC)"
            if last
            else "No committed imports"
        ),
    )
    if history.empty:
        _empty_state(
            "No import history", "Upload a file or run the CLI ingest command to create a batch."
        )
        return
    display = history.rename(
        columns={
            "import_id": "Import ID",
            "dataset": "Dataset",
            "source_file": "File",
            "status": "Status",
            "started_at": "Started",
            "completed_at": "Completed",
            "total_rows": "Rows",
            "inserted_rows": "Inserted",
            "updated_rows": "Updated",
            "unchanged_rows": "Unchanged",
            "rejected_rows": "Rejected",
            "error_message": "Error",
        }
    )
    for column in ("Started", "Completed"):
        display[column] = display[column].astype(str).str.replace("T", " ", regex=False)
    display = display.drop(columns=["Completed"])
    if display["Error"].isna().all() or (display["Error"].astype(str) == "None").all():
        display = display.drop(columns=["Error"])
    st.dataframe(display, hide_index=True, width="stretch")
    _download_csv(
        history, "import_history.csv", label="Download import history", key="history_download"
    )

    _section("Rejection report", "Select a batch to inspect row-level rejection reasons.")
    batch_options = ["All rejected records"] + history["import_id"].tolist()
    selected = st.selectbox("Batch", batch_options, key="rejection_batch_selector")
    import_id = None if selected == "All rejected records" else selected
    rejections = get_rejection_report(engine, import_id=import_id)
    if rejections.empty:
        st.info("No rejected rows are recorded for this selection.")
    else:
        st.dataframe(rejections, hide_index=True, width="stretch")
        _download_csv(
            rejections,
            f"rejections_{import_id or 'all'}.csv",
            label="Download rejection report",
            key="history_rejection_download",
        )


def _quality_tab(engine: Engine) -> None:
    try:
        checks = run_quality_checks(engine)
    except SalesPulseError as exc:
        st.error(str(exc))
        return
    _section(
        "Data-quality and reconciliation",
        "SQL integrity checks plus SQLite quick_check and PRAGMA foreign_key_check.",
    )
    _render_kpis(quality_cards(checks))
    failed = quality_failure_frame(checks)
    if failed.empty:
        st.success("All critical and warning checks pass against the current database.")
    else:
        st.warning(f"{len(failed)} check(s) need review. No values were silently repaired.")

    status_filter = st.selectbox(
        "Show checks",
        ["All checks", "Failures only", "Critical only", "Warnings only"],
        key="quality_filter",
    )
    filtered = checks
    if status_filter == "Failures only":
        filtered = checks[checks["status"] == "fail"]
    elif status_filter == "Critical only":
        filtered = checks[checks["severity"] == "critical"]
    elif status_filter == "Warnings only":
        filtered = checks[checks["severity"] == "warning"]
    display = filtered.drop(columns=["checked_at"], errors="ignore").rename(
        columns={
            "check_name": "Check",
            "severity": "Severity",
            "failures": "Failures",
            "status": "Status",
            "detail": "Detail",
            "recommended_action": "Recommended action",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")
    _download_csv(
        checks, "data_quality_report.csv", label="Download quality report", key="quality_download"
    )

    _section("Database reconciliation", "Row counts and integrity state from the live database.")
    counts = table_counts(engine)
    count_frame = pd.DataFrame([{"table": name, "rows": count} for name, count in counts.items()])
    st.dataframe(count_frame, hide_index=True, width="stretch")
    reconciliation = checks[checks["check_name"].str.contains("reconcil", case=False)]
    if not reconciliation.empty:
        st.dataframe(
            reconciliation[["check_name", "status", "failures", "detail"]],
            hide_index=True,
            width="stretch",
        )


def _imports_page(engine: Engine, settings: Settings) -> None:
    totals = get_import_totals(engine)
    last = get_last_import(engine)
    try:
        checks = run_quality_checks(engine)
        qsummary = quality_summary(checks)
    except SalesPulseError:
        qsummary = {"status": "unknown", "passed": 0, "checks": 0}
    _page_header(
        "Data operations",
        "Imports, rejections, and data quality",
        "This page reads the audit tables in SQLite. “Last import” means the latest committed "
        "batch, not a simulated live refresh.",
    )
    _render_kpis(
        [
            {
                "label": "Last import",
                "value": str(last["status"]).title() if last else "—",
                "help": (
                    f"{last['dataset']} · {int(last['total_rows']):,} rows · "
                    f"{int(last['rejected_rows']):,} rejected · {last['started_at']}"
                    if last
                    else "No committed imports"
                ),
            },
            {
                "label": "Processed records",
                "value": format_number(totals["processed_rows"]),
                "help": f"Across {totals['batches']:,} committed batches",
            },
            {
                "label": "Rejected records",
                "value": format_number(totals["rejected_rows"]),
                "help": "Stored with row numbers and reasons",
            },
            {
                "label": "Quality status",
                "value": str(qsummary["status"]).upper(),
                "help": f"{qsummary['passed']}/{qsummary['checks']} checks pass",
            },
            {
                "label": "Database",
                "value": "SQLite",
                "help": _display_path(settings.db_path),
            },
        ]
    )
    tab_upload, tab_history, tab_quality = st.tabs(
        ["Upload & validate", "Import history", "Quality checks"]
    )
    with tab_upload:
        _upload_tab(engine, settings)
    with tab_history:
        _history_tab(engine)
    with tab_quality:
        _quality_tab(engine)
    st.markdown(
        '<div class="sp-footer">All source data is synthetic. Rejections never silently '
        "alter business data; fixes must be made in the source and re-imported.</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    settings = Settings.from_env()
    if not settings.db_path.exists():
        _render_setup_required(
            settings, reason=f"Database not found: {_display_path(settings.db_path)}"
        )
    engine = _cached_engine(str(settings.db_path))
    if not is_initialized(engine):
        _render_setup_required(
            settings,
            reason="The file exists but does not contain the SalesPulse schema.",
        )
    service = AnalyticsService(engine)
    bounds = service.date_bounds()
    _render_brand()
    nav = st.sidebar.radio(
        "Navigation",
        [
            "Overview",
            "Product Performance",
            "Customer Analytics",
            "Geographic Analysis",
            "Data & Imports",
        ],
        label_visibility="collapsed",
    )
    st.sidebar.markdown('<div class="sp-divider"></div>', unsafe_allow_html=True)
    counts = table_counts(engine)
    st.sidebar.markdown(
        '<div class="sp-note"><strong>Demo dataset</strong><br>'
        f"{counts['customers']:,} fictional customers · {counts['products']:,} products · "
        f"{counts['orders']:,} orders<br>All records are synthetic.</div>",
        unsafe_allow_html=True,
    )

    if nav == "Data & Imports":
        _imports_page(engine, settings)
        return
    if bounds is None:
        _page_header(
            "No orders yet",
            "The database has no order data",
            "Import customers, products, orders, and order items to populate the dashboard.",
            pill="Empty database",
        )
        _empty_state(
            "No analytical data",
            "Use the Data & Imports page to load a source file, or run the demo command in "
            "the README. The dashboard never invents placeholder metrics.",
        )
        return
    start, end, _days = _date_filter(bounds)
    if nav == "Overview":
        _overview_page(engine, service, start, end)
    elif nav == "Product Performance":
        _product_page(engine, service, start, end)
    elif nav == "Customer Analytics":
        _customer_page(engine, service, start, end)
    elif nav == "Geographic Analysis":
        _regional_page(engine, service, start, end)


if __name__ == "__main__":
    main()
