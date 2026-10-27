"""Tests for normalization and money-rounding helpers."""

from __future__ import annotations

import pytest

from salespulse.transformations import (
    CATEGORIES,
    REGION_ALIASES,
    REGIONS,
    canonicalize,
    clean_text,
    normalize_email,
    parse_boolean,
    parse_decimal,
    parse_integer,
    round_money,
)


def test_clean_text_strips_controls_and_collapses_whitespace() -> None:
    assert clean_text("  Ada \t  Lovelace\x00  ") == "Ada Lovelace"
    assert clean_text(None) == ""
    assert clean_text(42) == "42"


def test_canonicalize_requires_documented_alias() -> None:
    assert canonicalize("  APAC ", REGION_ALIASES, REGIONS) == ("Asia-Pacific", None)
    value, error = canonicalize("Mars", REGION_ALIASES, REGIONS)
    assert value is None
    assert error is not None and "unsupported value" in error


def test_canonicalize_rejects_partial_or_case_only_matches() -> None:
    value, error = canonicalize(
        "electronics!", {item.lower(): item for item in CATEGORIES}, CATEGORIES
    )
    assert value is None
    assert error


def test_normalize_email_trims_and_lowercases() -> None:
    assert normalize_email("  Ada.Lovelace@Example.TEST ") == ("ada.lovelace@example.test", None)
    value, error = normalize_email("not-an-email")
    assert value is None
    assert error is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19.99", 19.99),
        ("$1,234.50", 1234.50),
        (" 8 ", 8.0),
        ("-5.00", -5.00),
    ],
)
def test_parse_decimal_accepts_common_formats(raw: str, expected: float) -> None:
    value, error = parse_decimal(raw, field_name="unit_price")
    assert error is None
    assert value == expected


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3"])
def test_parse_decimal_rejects_invalid_values(raw: str) -> None:
    value, error = parse_decimal(raw, field_name="unit_price")
    assert value is None
    assert error is not None


def test_parse_integer_enforces_bounds() -> None:
    assert parse_integer("5", field_name="quantity") == (5, None)
    value, error = parse_integer("1.5", field_name="quantity")
    assert value is None and error
    value, error = parse_integer("0", field_name="quantity", minimum=1)
    assert value is None and error


def test_parse_boolean_accepts_documented_tokens() -> None:
    for raw in ("1", "true", "YES", "y"):
        assert parse_boolean(raw) == (1, None)
    for raw in ("0", "false", "no", "N"):
        assert parse_boolean(raw) == (0, None)
    value, error = parse_boolean("maybe")
    assert value is None and error


def test_round_money_is_half_up_and_matches_sql_epsilon() -> None:
    assert round_money(66.955) == 66.96
    assert round_money(40.205) == 40.21
    assert round_money(33.376) == 33.38
    assert round_money(196.704) == 196.70
    with pytest.raises(ValueError):
        round_money("not money")
