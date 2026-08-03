from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

# Arabic-Indic digits -> ASCII, plus Arabic decimal/thousands separators
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CURRENCY_HINTS = {
    # \u20c1 is the new Saudi-Riyal sign. Safe to add: it denotes that one
    # currency and nothing else, unlike the spelled-out "ريال", which is
    # shared with the Qatari, Omani and Yemeni riyal — and which would win
    # on length over "ر.ق", reading a Qatari page as SAR.
    #
    # Extra renders it, but never sends it: zero occurrences in the served
    # HTML of both reference pages, in any encoding. The markup says the
    # ASCII string "SAR" and the glyph is drawn client-side, so this entry
    # changes nothing for ExtraTracker. It is here for callers that pass in
    # text copied from a rendered page.
    "SAR": ("sar", "ر.س", "﷼", "\u20c1", "sr "),
    "AED": ("aed", "د.إ", "dhs", "dirham"),
    "QAR": ("qar", "ر.ق"),
    "KWD": ("kwd", "د.ك"),
    "BHD": ("bhd", "د.ب"),
    "OMR": ("omr", "ر.ع"),
    "EGP": ("egp", "ج.م"),
    "JOD": ("jod", "د.ا"),
    "USD": ("usd", "us$", "$"),
    "EUR": ("eur", "€"),
    "GBP": ("gbp", "£"),
    "JPY": ("jpy", "¥", "円"),
    "CNY": ("cny", "rmb", "元"),
    "INR": ("inr", "₹", "rs."),
    "TRY": ("try", "₺"),
    "RUB": ("rub", "₽"),
    "KRW": ("krw", "₩"),
    "CHF": ("chf",),
    "SEK": ("sek", "kr"),
    "PLN": ("pln", "zł"),
    "BRL": ("brl", "r$"),
    "CAD": ("cad", "c$"),
    "AUD": ("aud", "a$"),
    "ZAR": ("zar",),
}

# Ambiguous symbols must lose to their qualified forms: "C$" is CAD, not
# USD. Longest hint wins, so check in descending length order.
_HINTS_ORDERED = sorted(
    ((h, code) for code, hints in _CURRENCY_HINTS.items() for h in hints),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


# Separators that carry no numeric meaning anywhere: RTL marks, NBSP,
# thin spaces, and the Arabic thousands mark.
_NOISE = dict.fromkeys(map(ord, "\u200f\u200e\u202b\u202c\u00a0\u2009\u066c\u2019'"), None)

# A run of digits possibly broken by separators — grabbed before any
# separator logic runs, so a currency symbol containing a dot ("ر.س")
# can never be mistaken for part of the number.
_NUMBER_RE = re.compile(r"\d[\d.,\s]*\d|\d")


def _normalize_separators(token: str) -> str:
    """Resolve '.' and ',' into a single ASCII decimal point.

    1,299.00 (US) and 1.299,50 (EU) both mean the same amount. Guessing
    wrong inflates a price 100x or deflates it 1000x, which is worse
    than failing outright — a bot would fire a bogus price-drop alert.
    """
    token = re.sub(r"\s", "", token)
    has_dot, has_comma = "." in token, "," in token

    if has_dot and has_comma:
        # Whichever comes last is the decimal point; the other groups
        # thousands. True for both 1,299.00 and 1.299,50.
        if token.rfind(".") > token.rfind(","):
            token = token.replace(",", "")
        else:
            token = token.replace(".", "").replace(",", ".")
        return token

    if not (has_dot or has_comma):
        return token

    sep = "." if has_dot else ","
    if token.count(sep) > 1:
        # 1.234.567 — repetition can only mean grouping.
        return token.replace(sep, "")

    tail = len(token.rsplit(sep, 1)[1])
    if tail == 3:
        # 1,299 / 1.299 — exactly three trailing digits is grouping.
        # Prices are not quoted to three decimals, so this is safe.
        return token.replace(sep, "")
    return token.replace(sep, ".")


def parse_price(raw: Any) -> Optional[Decimal]:
    """Turn anything a site throws at us into a Decimal, or None.

    Locale-agnostic: handles Arabic-Indic and Persian digits, the Arabic
    decimal mark, US grouping (1,299.00), European grouping (1.299,50),
    French spacing (1 299,50), and symbols glued to the number.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))

    text = str(raw).translate(_DIGIT_MAP).translate(_NOISE)
    text = text.replace("\u066b", ",")   # Arabic decimal mark
    text = text.replace("\u066c", "")    # Arabic thousands mark

    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(_normalize_separators(match.group()))
    except InvalidOperation:
        return None


def detect_currency(text: Optional[str], default: str = "SAR") -> str:
    """Best-effort currency detection from a price string.

    Longest hint wins so "C$" resolves to CAD rather than matching the
    bare "$" of USD.
    """
    if not text:
        return default
    low = str(text).lower()
    for hint, code in _HINTS_ORDERED:
        if hint in low:
            return code
    return default


@dataclass(frozen=True, slots=True)
class Product:
    """A single price observation for a product page."""

    name: str
    price: Optional[Decimal]
    currency: str
    url: str
    site: str
    in_stock: Optional[bool] = None
    image: Optional[str] = None
    sku: Optional[str] = None
    list_price: Optional[Decimal] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), compare=False
    )

    @property
    def has_price(self) -> bool:
        return self.price is not None

    @property
    def discount_pct(self) -> Optional[Decimal]:
        """How far below the advertised list price, or None if not on offer.

        Returns None rather than 0 when there is no list price — absent
        and zero mean different things to a price alert.
        """
        if self.price is None or self.list_price is None:
            return None
        if self.list_price <= 0 or self.list_price <= self.price:
            return None
        drop = (self.list_price - self.price) / self.list_price * 100
        return drop.quantize(Decimal("0.1"))

    def cheaper_than(self, other: "Product") -> bool:
        """Compare against another observation. Same currency required."""
        if not (self.has_price and other.has_price):
            raise ValueError("Cannot compare products without a price.")
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: {self.currency} vs {other.currency}"
            )
        return self.price < other.price

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        data["price"] = str(self.price) if self.price is not None else None
        data["list_price"] = (
            str(self.list_price) if self.list_price is not None else None
        )
        data["fetched_at"] = self.fetched_at.isoformat()
        return data

    def __str__(self) -> str:
        price = f"{self.price} {self.currency}" if self.has_price else "N/A"
        return f"{self.name} — {price} ({self.site})"