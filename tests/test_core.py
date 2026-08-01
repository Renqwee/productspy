"""Offline tests — no network, no real sites.

Run with:  pytest -v
"""

from decimal import Decimal

import pytest

import productspy as ps
from productspy import BlockedError, FetchError, ParseError, UnsupportedSiteError
from productspy.base import BaseTracker
from productspy.http import FetchConfig, Fetcher
from productspy.models import Product, detect_currency, parse_price


# --------------------------------------------------------------------
# Price parsing — the layer that broke most often in the old code
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("399.00 SAR", Decimal("399.00")),
        ("1,299.00", Decimal("1299.00")),
        ("٣٩٩٫٥٠ ر.س", Decimal("399.50")),          # Arabic-Indic digits
        ("۱۲۳٫۴۵", Decimal("123.45")),               # Persian digits
        ("\u200f450 ريال", Decimal("450")),          # hidden RTL mark
        ("SAR 89", Decimal("89")),
        (1499, Decimal("1499")),
        (99.5, Decimal("99.5")),
        (Decimal("10"), Decimal("10")),
        (None, None),
        ("", None),
        ("Out of stock", None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_float_precision_is_preserved():
    """The whole reason we use Decimal instead of float."""
    total = parse_price("0.1") + parse_price("0.2")
    assert total == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3  # what we avoided


@pytest.mark.parametrize(
    "text, expected",
    [
        ("399 ر.س", "SAR"),
        ("100 AED", "AED"),
        ("$45.99", "USD"),
        ("no currency here", "SAR"),  # falls back to default
    ],
)
def test_detect_currency(text, expected):
    assert detect_currency(text) == expected


# --------------------------------------------------------------------
# Product model
# --------------------------------------------------------------------

def _product(price, currency="SAR", name="Test"):
    return Product(
        name=name, price=price, currency=currency, url="http://x", site="Test"
    )


def test_cheaper_than():
    assert _product(Decimal("100")).cheaper_than(_product(Decimal("120")))
    assert not _product(Decimal("120")).cheaper_than(_product(Decimal("100")))


def test_currency_mismatch_raises():
    """A silent SAR-vs-USD comparison would send a false price-drop alert."""
    with pytest.raises(ValueError, match="Currency mismatch"):
        _product(Decimal("100"), "SAR").cheaper_than(_product(Decimal("100"), "USD"))


def test_missing_price_raises():
    with pytest.raises(ValueError):
        _product(None).cheaper_than(_product(Decimal("50")))


def test_product_is_immutable():
    p = _product(Decimal("10"))
    with pytest.raises(Exception):
        p.price = Decimal("5")


def test_to_dict_is_json_safe():
    import json

    data = _product(Decimal("399.50")).to_dict()
    assert data["price"] == "399.50"          # str, not Decimal
    assert "raw" not in data
    json.dumps(data)                           # must not raise


# --------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------

def test_unsupported_site():
    with pytest.raises(UnsupportedSiteError):
        ps.get_product_info("https://example.com/product/123")


def test_longest_pattern_wins():
    from productspy.registry import register, resolve_tracker

    @register("zzz-shop.")
    class Generic(BaseTracker):
        site_name = "Generic"

        def parse(self, soup, html):
            return {}

    @register("zzz-shop.sa")
    class Local(BaseTracker):
        site_name = "Local"

        def parse(self, soup, html):
            return {}

    assert resolve_tracker("zzz-shop.com") is Generic
    assert resolve_tracker("zzz-shop.sa") is Local


# --------------------------------------------------------------------
# JSON-LD extraction — including the nesting the old code missed
# --------------------------------------------------------------------

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Wireless Mouse","sku":"ABC123",
 "image":["https://cdn.test/1.jpg"],
 "offers":{"@type":"Offer","price":"149.00","priceCurrency":"SAR",
           "availability":"https://schema.org/InStock"}}
</script>
</head><body><h1>Wireless Mouse</h1></body></html>
"""

NESTED_GRAPH_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebSite","name":"Some Shop"},
  {"@type":["Product","Thing"],"name":"Nested Item",
   "offers":{"price":"75.50","priceCurrency":"AED",
             "availability":"https://schema.org/OutOfStock"}}
]}
</script>
</head><body></body></html>
"""


def _soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def test_json_ld_flat():
    data = BaseTracker.from_json_ld(BaseTracker.find_json_ld_product(_soup(JSON_LD_PAGE)))
    assert data["name"] == "Wireless Mouse"
    assert parse_price(data["price"]) == Decimal("149.00")
    assert data["currency"] == "SAR"
    assert data["in_stock"] is True
    assert data["image"] == "https://cdn.test/1.jpg"   # list -> first item


def test_json_ld_nested_in_graph():
    """The old code only checked the top level and failed on this shape."""
    found = BaseTracker.find_json_ld_product(_soup(NESTED_GRAPH_PAGE))
    assert found is not None
    data = BaseTracker.from_json_ld(found)
    assert data["name"] == "Nested Item"
    assert data["in_stock"] is False
    assert data["currency"] == "AED"


def test_json_ld_absent_returns_none():
    assert BaseTracker.find_json_ld_product(_soup("<html><body>hi</body></html>")) is None


def test_malformed_json_ld_does_not_crash():
    broken = '<script type="application/ld+json">{not json at all</script>'
    assert BaseTracker.find_json_ld_product(_soup(broken)) is None


# --------------------------------------------------------------------
# HTTP layer — block detection is the part that stalled the old project
# --------------------------------------------------------------------

def test_blocked_is_catchable_as_fetch_error():
    """Inheritance contract: BlockedError must satisfy `except FetchError`."""
    assert issubclass(BlockedError, FetchError)


def test_browser_headers_present():
    """Missing Sec-Fetch-* headers are a bot signal."""
    headers = Fetcher().headers()
    for key in ("User-Agent", "Accept-Language", "Sec-Fetch-Mode"):
        assert key in headers


def test_proxy_rotation_cycles():
    fetcher = Fetcher(FetchConfig(proxies=["http://a:1", "http://b:2"]))
    seen = [fetcher._next_proxy()["https"] for _ in range(4)]
    assert seen == ["http://a:1", "http://b:2", "http://a:1", "http://b:2"]


def test_no_proxy_returns_none():
    assert Fetcher(FetchConfig())._next_proxy() is None