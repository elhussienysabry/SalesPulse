"""Streamlit smoke tests using the framework's AppTest harness."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from salespulse.config import PROJECT_ROOT

APP_PATH = PROJECT_ROOT / "app.py"
PAGES = (
    "Overview",
    "Product Performance",
    "Customer Analytics",
    "Geographic Analysis",
    "Data & Imports",
)


def test_all_dashboard_pages_render_without_exceptions(clean_engine, monkeypatch) -> None:
    assert Path(str(clean_engine.url.database)).exists()
    monkeypatch.setenv("SALESPULSE_DB_PATH", str(clean_engine.url.database))
    app = AppTest.from_file(str(APP_PATH), default_timeout=90)
    app.run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "Overview"

    for page in PAGES[1:]:
        app.sidebar.radio[0].set_value(page)
        app.run()
        assert not app.exception, (page, app.exception)


def test_missing_database_shows_setup_guidance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SALESPULSE_DB_PATH", str(tmp_path / "missing.db"))
    app = AppTest.from_file(str(APP_PATH), default_timeout=90)
    app.run()
    assert not app.exception
    assert app.warning
    assert "Database not found" in app.warning[0].value
    assert any("demo --reset" in markdown.value for markdown in app.markdown)
