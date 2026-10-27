"""Canonical values and documented text normalization helpers.

Normalization is intentionally narrow: whitespace is trimmed, emails are
lower-cased, and known categorical aliases are mapped to canonical values.
Nothing else is "cleaned" silently. Unknown values are rejected so a human can
decide what they mean.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

REGIONS = (
    "North America",
    "Europe",
    "Asia-Pacific",
    "Latin America",
    "Middle East & Africa",
)
CATEGORIES = (
    "Electronics",
    "Home & Kitchen",
    "Office",
    "Sports & Outdoor",
    "Beauty",
    "Accessories",
)
ORDER_STATUSES = ("completed", "pending", "cancelled")
RETURN_STATUSES = ("approved", "requested", "rejected")
RETURN_REASONS = (
    "damaged",
    "wrong_item",
    "not_as_described",
    "changed_mind",
    "late_delivery",
    "other",
)
PAYMENT_METHODS = ("card", "paypal", "bank_transfer", "cash_on_delivery")
PAYMENT_STATUSES = ("paid", "pending", "failed")

# Aliases are matched after case-folding and whitespace collapsing.
REGION_ALIASES = {
    "north america": "North America",
    "north-america": "North America",
    "na": "North America",
    "europe": "Europe",
    "eu": "Europe",
    "emea": "Europe",
    "asia-pacific": "Asia-Pacific",
    "asia pacific": "Asia-Pacific",
    "apac": "Asia-Pacific",
    "asia": "Asia-Pacific",
    "latin america": "Latin America",
    "latam": "Latin America",
    "south america": "Latin America",
    "middle east & africa": "Middle East & Africa",
    "middle east and africa": "Middle East & Africa",
    "mea": "Middle East & Africa",
    "africa": "Middle East & Africa",
}

CATEGORY_ALIASES = {
    "electronics": "Electronics",
    "electronic": "Electronics",
    "home & kitchen": "Home & Kitchen",
    "home and kitchen": "Home & Kitchen",
    "home kitchen": "Home & Kitchen",
    "kitchen": "Home & Kitchen",
    "office": "Office",
    "office supplies": "Office",
    "sports & outdoor": "Sports & Outdoor",
    "sports and outdoor": "Sports & Outdoor",
    "sports": "Sports & Outdoor",
    "outdoor": "Sports & Outdoor",
    "beauty": "Beauty",
    "personal care": "Beauty",
    "accessories": "Accessories",
    "accessory": "Accessories",
}

ORDER_STATUS_ALIASES = {
    "completed": "completed",
    "complete": "completed",
    "done": "completed",
    "fulfilled": "completed",
    "pending": "pending",
    "processing": "pending",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "void": "cancelled",
}

RETURN_STATUS_ALIASES = {
    "approved": "approved",
    "accepted": "approved",
    "requested": "requested",
    "pending": "requested",
    "rejected": "rejected",
    "denied": "rejected",
}

RETURN_REASON_ALIASES = {
    "damaged": "damaged",
    "broken": "damaged",
    "wrong_item": "wrong_item",
    "wrong item": "wrong_item",
    "not_as_described": "not_as_described",
    "not as described": "not_as_described",
    "changed_mind": "changed_mind",
    "changed mind": "changed_mind",
    "late_delivery": "late_delivery",
    "late delivery": "late_delivery",
    "other": "other",
}

PAYMENT_METHOD_ALIASES = {
    "card": "card",
    "credit card": "card",
    "credit_card": "card",
    "debit card": "card",
    "paypal": "paypal",
    "pay pal": "paypal",
    "bank_transfer": "bank_transfer",
    "bank transfer": "bank_transfer",
    "banktransfer": "bank_transfer",
    "cash_on_delivery": "cash_on_delivery",
    "cash on delivery": "cash_on_delivery",
    "cod": "cash_on_delivery",
}

PAYMENT_STATUS_ALIASES = {
    "paid": "paid",
    "settled": "paid",
    "complete": "paid",
    "pending": "pending",
    "failed": "failed",
    "declined": "failed",
}

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_RE = re.compile(r"\s+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def round_money(value: object) -> float:
    """Round a monetary amount to cents using half-up semantics.

    SQLite's ROUND() and Python's round() both operate on binary floats and
    disagree on exact half-cent values (for example 66.955). The small epsilon
    makes our Python-side calculation deterministic and consistent with the
    +1e-9 epsilon used in the SQL views, so order totals and payment amounts
    reconcile exactly.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a monetary amount: {value!r}") from exc
    return round(number + 1e-9, 2)


def clean_text(value: object) -> str:
    """Trim, collapse internal whitespace, and strip control characters."""
    if value is None:
        return ""
    text = str(value)
    text = CONTROL_CHARS_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_key(value: str) -> str:
    """Case/whitespace-insensitive lookup key for categorical aliases."""
    return clean_text(value).casefold()


def canonicalize(
    value: str,
    aliases: dict[str, str],
    allowed: tuple[str, ...],
) -> tuple[str | None, str | None]:
    """Return (canonical_value, error_message)."""
    raw = clean_text(value)
    if not raw:
        return None, "value is required"
    canonical = aliases.get(normalize_key(raw))
    if canonical is None and raw in allowed:
        canonical = raw
    if canonical is None:
        allowed_list = ", ".join(allowed)
        return None, f"unsupported value {raw!r}; expected one of: {allowed_list}"
    return canonical, None


def normalize_email(value: object) -> tuple[str | None, str | None]:
    email = clean_text(value).lower()
    if not email:
        return None, "value is required"
    if not EMAIL_RE.match(email):
        return None, f"invalid email address {email!r}"
    return email, None


def parse_decimal(
    value: object,
    *,
    field_name: str,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    max_places: int = 2,
) -> tuple[float | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, f"missing required field {field_name!r}"
    formatted = raw.replace("$", "").replace(",", "")
    if formatted.startswith("(") and formatted.endswith(")"):
        formatted = f"-{formatted[1:-1]}"
    try:
        number = Decimal(formatted)
    except InvalidOperation:
        return None, f"{field_name} must be a number, got {raw!r}"
    if not number.is_finite():
        return None, f"{field_name} must be finite"
    if number.as_tuple().exponent < -max_places:
        return None, f"{field_name} must have at most {max_places} decimal places"
    if minimum is not None and number < minimum:
        return None, f"{field_name} must be >= {minimum}"
    if maximum is not None and number > maximum:
        return None, f"{field_name} must be <= {maximum}"
    return float(number), None


def parse_integer(
    value: object,
    *,
    field_name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> tuple[int | None, str | None]:
    raw = clean_text(value)
    if not raw:
        return None, f"missing required field {field_name!r}"
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None, f"{field_name} must be an integer, got {raw!r}"
    if not number.is_finite() or number != number.to_integral_value():
        return None, f"{field_name} must be a whole number, got {raw!r}"
    integer = int(number)
    if minimum is not None and integer < minimum:
        return None, f"{field_name} must be >= {minimum}"
    if maximum is not None and integer > maximum:
        return None, f"{field_name} must be <= {maximum}"
    return integer, None


def parse_boolean(value: object, *, field_name: str = "is_active") -> tuple[int | None, str | None]:
    raw = normalize_key(clean_text(value))
    if raw in {"1", "true", "yes", "y", "active"}:
        return 1, None
    if raw in {"0", "false", "no", "n", "inactive"}:
        return 0, None
    return None, f"{field_name} must be 0/1 or true/false, got {value!r}"
