"""Locale-agnostic parsing — the library must work outside the Gulf.

A misread separator is worse than a failed parse: 19,99 EUR read as
1999 would fire a fake price-drop alert every single run.
"""

from decimal import Decimal

import pytest

from productspy.base import BaseTracker
from productspy.models import detect_currency, parse_price
from productspy.utils.url_tools import currency_from_domain


# --------------------------------------------------------------------
# Number formats
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        # US / UK grouping
        ("1,299.00", Decimal("1299.00")),
        ("1,234,567.89", Decimal("1234567.89")),
        ("$1,500", Decimal("1500")),
        ("£19.99", Decimal("19.99")),
        # European grouping — comma is the decimal point
        ("1.299,50 €", Decimal("1299.50")),
        ("19,99 €", Decimal("19.99")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("2.000,00 zł", Decimal("2000.00")),
        # French: space groups thousands
        ("1 299,50 €", Decimal("1299.50")),
        ("1\u00a0299,50", Decimal("1299.50")),   # non-breaking space
        # Indian lakh grouping
        ("₹1,29,999", Decimal("129999")),
        # Bare thousands, no decimals
        ("1,299", Decimal("1299")),
        ("1.299", Decimal("1299")),
        # Arabic-Indic and Persian
        ("٣٩٩٫٥٠ ر.س", Decimal("399.50")),
        ("۱۲۳٫۴۵", Decimal("123.45")),
        ("\u200f450 ريال", Decimal("450")),
        # Currency symbol containing a dot must not join the number
        ("399.00 ر.س", Decimal("399.00")),
        ("ر.س 89", Decimal("89")),
        # Nothing numeric
        ("Out of stock", None),
        ("Contact us for price", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_price_across_locales(raw, expected):
    assert parse_price(raw) == expected


def test_european_decimal_is_not_inflated():
    """The regression this guards: 19,99 must never become 1999."""
    assert parse_price("19,99 €") < Decimal("20")


def test_us_thousands_is_not_deflated():
    """And 1,299.00 must never become 1.29900."""
    assert parse_price("1,299.00") > Decimal("1000")


# --------------------------------------------------------------------
# Currency detection
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("399 ر.س", "SAR"),
        ("100 AED", "AED"),
        ("$45.99", "USD"),
        ("19,99 €", "EUR"),
        ("£20", "GBP"),
        ("¥1200", "JPY"),
        ("₹999", "INR"),
        ("₺500", "TRY"),
        ("no currency here", "SAR"),  # falls back to the given default
    ],
)
def test_detect_currency(text, expected):
    assert detect_currency(text) == expected


def test_qualified_symbol_beats_bare_dollar():
    """C$ is Canadian, not a US dollar with a stray letter."""
    assert detect_currency("C$30") == "CAD"
    assert detect_currency("R$50") == "BRL"
    assert detect_currency("A$25") == "AUD"


# --------------------------------------------------------------------
# Currency from domain
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "domain, expected",
    [
        ("amazon.sa", "SAR"),
        ("amazon.ae", "AED"),
        ("amazon.co.uk", "GBP"),
        ("amazon.de", "EUR"),
        ("amazon.fr", "EUR"),
        ("amazon.com", "USD"),
        ("amazon.com.au", "AUD"),
        ("amazon.co.jp", "JPY"),
        ("amazon.in", "INR"),
        ("ebay.pl", "PLN"),
        ("shop.example.xyz", "USD"),  # unknown TLD -> default
        (None, "USD"),
        ("", "USD"),
    ],
)
def test_currency_from_domain(domain, expected):
    assert currency_from_domain(domain) == expected


# --------------------------------------------------------------------
# The fallback chain inside BaseTracker
# --------------------------------------------------------------------

class _Stub(BaseTracker):
    site_name = "Stub"

    def parse(self, soup, html):
        return {}


def test_fallback_currency_follows_the_tld():
    assert _Stub("https://amazon.de/dp/X").fallback_currency == "EUR"
    assert _Stub("https://amazon.sa/dp/X").fallback_currency == "SAR"


def test_explicit_default_currency_wins_over_tld():
    """noon.com is a .com but quotes SAR — the tracker must be able to say so."""

    class _Noonish(_Stub):
        default_currency = "SAR"

    assert _Noonish("https://www.noon.com/p").fallback_currency == "SAR"
    assert _Stub("https://www.noon.com/p").fallback_currency == "USD"