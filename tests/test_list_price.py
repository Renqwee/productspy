"""list_price plumbing: trackers extract it, fetch() must not drop it."""

import json
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from productspy.base import BaseTracker
from productspy.models import Product


def _product(price, list_price=None):
    return Product(
        name="Test",
        price=price,
        currency="SAR",
        url="http://x",
        site="Test",
        list_price=list_price,
    )


# --------------------------------------------------------------------
# discount_pct
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "price, list_price, expected",
    [
        (Decimal("3309"), Decimal("3899"), Decimal("15.1")),
        (Decimal("50"), Decimal("100"), Decimal("50.0")),
        (Decimal("100"), None, None),            # no list price advertised
        (None, Decimal("100"), None),            # no price at all
        (Decimal("100"), Decimal("100"), None),  # not actually a discount
        (Decimal("120"), Decimal("100"), None),  # list below price — bogus
        (Decimal("10"), Decimal("0"), None),     # guard against /0
    ],
)
def test_discount_pct(price, list_price, expected):
    assert _product(price, list_price).discount_pct == expected


def test_discount_absent_is_none_not_zero():
    """A price alert must tell 'no offer' apart from 'offer worth 0%'."""
    assert _product(Decimal("100")).discount_pct is None


# --------------------------------------------------------------------
# to_dict stays JSON-safe
# --------------------------------------------------------------------

def test_to_dict_serialises_list_price_as_string():
    data = _product(Decimal("3309"), Decimal("3899.00")).to_dict()
    assert data["list_price"] == "3899.00"
    json.dumps(data)


def test_to_dict_list_price_none_stays_none():
    data = _product(Decimal("3309")).to_dict()
    assert data["list_price"] is None
    json.dumps(data)


# --------------------------------------------------------------------
# fetch() must carry it through — the bug this fixes
# --------------------------------------------------------------------

class _FakeResponse:
    status_code = 200
    url = "http://shop.test/p"
    text = "<html><body><h1>x</h1></body></html>"


class _FakeFetcher:
    def get(self, url, **kwargs):
        return _FakeResponse()


class _StubTracker(BaseTracker):
    site_name = "Stub"

    def parse(self, soup, html):
        return {
            "name": "Widget",
            "price": "3309",
            "currency": "SAR",
            "list_price": "3899",
        }


def test_fetch_carries_list_price_into_product():
    product = _StubTracker("http://shop.test/p", fetcher=_FakeFetcher()).fetch()
    assert product.list_price == Decimal("3899")
    assert product.price == Decimal("3309")
    assert product.discount_pct == Decimal("15.1")


class _NoListPriceTracker(_StubTracker):
    def parse(self, soup, html):
        return {"name": "Widget", "price": "99", "currency": "SAR"}


def test_fetch_without_list_price_is_none():
    product = _NoListPriceTracker("http://shop.test/p", fetcher=_FakeFetcher()).fetch()
    assert product.list_price is None
    assert product.discount_pct is None


# --------------------------------------------------------------------
# Noon's strikethrough extraction
# --------------------------------------------------------------------

STRIKETHROUGH_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Phone",
 "offers":{"@type":"Offer","price":"3309","priceCurrency":"SAR",
           "availability":"https://schema.org/InStock",
           "priceSpecification":{"priceType":"https://schema.org/StrikethroughPrice",
                                 "price":"3899"}}}
</script>
</head><body></body></html>
"""


def test_noon_picks_up_strikethrough_price():
    from productspy.trackers.noon import NoonTracker

    soup = BeautifulSoup(STRIKETHROUGH_PAGE, "html.parser")
    tracker = NoonTracker("https://www.noon.com/p", fetcher=_FakeFetcher())
    data = tracker.parse(soup, STRIKETHROUGH_PAGE)
    assert data["list_price"] == "3899"