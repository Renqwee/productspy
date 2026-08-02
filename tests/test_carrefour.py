"""CarrefourTracker.

The fixtures here are cut from a real PDP (SKU 733391, AirPods Pro 2,
selling 709.00 SAR, was 1049.00, discount 340) fetched with ?sid=EXPRESS:
the JSON-LD block, the escaped RSC flight chunks, and the analytics
object with its oneGM* decoys are reproduced verbatim in shape.

The headline case is test_json_ld_price_is_the_discount_and_is_ignored —
Carrefour puts the discount amount in offers.price, so trusting schema.org
here would track a 709 SAR product as a 340 SAR one.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from productspy import UnsupportedSiteError
from productspy.registry import resolve_tracker
from productspy.trackers.carrefour import CarrefourTracker


LIVE_URL = (
    "https://www.carrefourksa.com/mafsau/en/true-wireless-earbuds/"
    "apple-airpods-pro-2-with-ms-usb-c/p/733391"
)
LIVE_URL_SID = LIVE_URL + "?sid=EXPRESS"


class _FakeResponse:
    status_code = 200
    url = LIVE_URL_SID
    text = "<html><body><h1>x</h1></body></html>"


class _FakeFetcher:
    def __init__(self, html=None):
        self.html = html

    def get(self, url, **kwargs):
        response = _FakeResponse()
        if self.html is not None:
            response.text = self.html
        return response


def _tracker(url=LIVE_URL):
    return CarrefourTracker(url, fetcher=_FakeFetcher())


def _soup(html):
    return BeautifulSoup(html, "html.parser")


# --------------------------------------------------------------------
# Fixtures cut from the live page
# --------------------------------------------------------------------

JSON_LD = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Apple AirPods Pro 2nd Gen USB-C Earbuds (MTJV3ZEA)",
 "image":"https://cdn.mafrservices.com/sys-master-root/h0e/h5b/63607269261342/733391_main.jpg",
 "brand":"nonfood_apple","sku":"733391","productCategory":"nfksa1200000",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"340",
           "availability":"https://schema.org/InStock",
           "url":"https://www.carrefourksa.com/mafsau/en/p/733391",
           "itemCondition":"https://schema.org/NewCondition"}}
</script>
"""

# Escaped exactly the way Next.js streams it.
FLIGHT = r"""
<script>self.__next_f.push([1,"a3:{\"brandName\":\"nonfood_apple\",\"itemVariant\":\"not_applicable\",\"affiliation\":\"carrefour\",\"oneGMSellingPrice\":0.709,\"oneGMMarkedPrice\":1.049,\"unitPrice\":1049,\"effectiveUnit\":1,\"effectiveUnitPrice\":1049,\"promotion_tag\":\"\"}\n"])</script>
<script>self.__next_f.push([1,"b7:{\"image\":\"https://cdn.mafrservices.com/sys-master-root/h0e/h5b/63607269261342/733391_main.jpg\",\"shopId\":\"0000\",\"shopName\":\"Carrefour\",\"discount\":\"340\",\"price\":\"709.00\",\"orderThresholdMax\":1,\"countryCode\":\"SA\",\"currencyISO\":\"SAR\"}\n"])</script>
<script>self.__next_f.push([1,"c4:{\"currency\":\"SAR\",\"currencySymbol\":\"\",\"finalPrice\":\"709.00\",\"vatText\":\"Including VAT\"}\n"])</script>
"""

BODY = """
<html><head>
<meta property="og:title" content="Buy Apple AirPods Pro 2 Online | Carrefour KSA">
<meta property="og:image" content="https://cdn.mafrservices.com/sys-master-root/h0e/h5b/63607269261342/733391_main.jpg">
{ld}</head><body>
<h1>Apple AirPods Pro 2nd Gen USB-C Earbuds (MTJV3ZEA)</h1>
{flight}
</body></html>
"""

FULL_PAGE = BODY.format(ld=JSON_LD, flight=FLIGHT)


# --------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------

def test_resolve_tracker_carrefour():
    assert resolve_tracker("carrefourksa.com") is CarrefourTracker


@pytest.mark.parametrize(
    "domain",
    [
        "mycarrefourksa.com",             # someone else's shop
        "carrefourksa.com.attacker.net",  # phishing host ending elsewhere
        "carrefouruae.com",               # same platform, different currency
        "carrefour.com",
    ],
)
def test_lookalike_and_sibling_domains_are_rejected(domain):
    with pytest.raises(UnsupportedSiteError):
        resolve_tracker(domain)


# --------------------------------------------------------------------
# URL handling — sid is load-bearing
# --------------------------------------------------------------------

def test_sid_survives_and_everything_else_is_dropped():
    dirty = LIVE_URL + "?offer=offer_carrefour_&sid=EXPRESS&sellerId=0000#reviews"
    assert _tracker(dirty).url == LIVE_URL_SID


def test_sid_is_injected_when_the_url_arrives_clean():
    """A link copied from search has no sid, and without one the page
    renders out of stock with no price at all."""
    assert _tracker(LIVE_URL).url == LIVE_URL_SID


def test_a_non_default_sid_is_respected_not_replaced():
    scheduled = LIVE_URL + "?sid=SCHEDULED"
    assert _tracker(scheduled).url == scheduled


def test_the_same_product_from_three_places_normalises_to_one_url():
    variants = [
        LIVE_URL,
        LIVE_URL + "?utm_source=ads",
        LIVE_URL + "?sid=EXPRESS&sellerId=0000",
        LIVE_URL + "#reviews",
    ]
    assert len({_tracker(u).url for u in variants}) == 1


@pytest.mark.parametrize(
    "url, sku",
    [
        (LIVE_URL, "733391"),                        # short numeric
        ("https://www.carrefourksa.com/mafsau/en/smartphones/"
         "apple-iphone-11-/p/SA190199220423", "SA190199220423"),  # supplier code
    ],
)
def test_both_live_sku_shapes_parse(url, sku):
    assert CarrefourTracker._sku_from_url(url) == sku


# --------------------------------------------------------------------
# The bug this tracker exists to avoid
# --------------------------------------------------------------------

def test_json_ld_price_is_the_discount_and_is_ignored():
    """offers.price is 340 on the live page. The product costs 709."""
    data = _tracker().parse(_soup(FULL_PAGE), FULL_PAGE)
    assert data["price"] == "709.00"
    assert data["price"] != "340"


def test_analytics_decoys_are_not_mistaken_for_the_price():
    """oneGMSellingPrice 0.709 / oneGMMarkedPrice 1.049 sit in the same
    object as the real figures, a thousand times too small."""
    data = _tracker().parse(_soup(FULL_PAGE), FULL_PAGE)
    assert Decimal(data["price"]) > 1
    assert Decimal(data["list_price"]) > 1


def test_list_price_comes_from_unit_price():
    data = _tracker().parse(_soup(FULL_PAGE), FULL_PAGE)
    assert data["list_price"] == "1049"


def test_json_ld_still_supplies_the_non_price_fields():
    data = _tracker().parse(_soup(FULL_PAGE), FULL_PAGE)
    assert data["name"].startswith("Apple AirPods Pro 2nd Gen")
    assert data["sku"] == "733391"
    assert data["currency"] == "SAR"
    assert data["in_stock"] is True
    assert data["image"].endswith("733391_main.jpg")


def test_fetch_end_to_end():
    product = CarrefourTracker(LIVE_URL, fetcher=_FakeFetcher(FULL_PAGE)).fetch()
    assert product.price == Decimal("709.00")
    assert product.list_price == Decimal("1049")
    assert product.discount_pct == Decimal("32.4")   # 340 / 1049
    assert product.currency == "SAR"
    assert product.site == "Carrefour"
    assert product.in_stock is True


# --------------------------------------------------------------------
# Anchoring: carousels carry their own prices
# --------------------------------------------------------------------

FILLER = "<!-- " + ("x" * 3000) + " -->"

CAROUSEL_FIRST = BODY.format(
    ld=JSON_LD,
    flight=(
        r"""<script>self.__next_f.push([1,"z1:{\"image\":\"https://cdn.mafrservices.com/x/999999_main.jpg\",\"shopId\":\"0000\",\"price\":\"99.00\"}\n"])</script>"""
        + FILLER
        + FLIGHT
    ),
)


def test_a_recommendation_price_earlier_in_the_payload_is_skipped():
    """Every carousel card ships its own "price" key. Only the number
    sitting near this product's SKU counts."""
    data = _tracker().parse(_soup(CAROUSEL_FIRST), CAROUSEL_FIRST)
    assert data["price"] == "709.00"


# --------------------------------------------------------------------
# Degraded pages
# --------------------------------------------------------------------

NO_FLIGHT_PAGE = BODY.format(ld=JSON_LD, flight="")


def test_without_the_flight_payload_there_is_no_price():
    """What a sid-less or genuinely out-of-stock fetch looks like: the
    price components are simply not emitted. None, never the JSON-LD
    discount, and never a fabricated 0."""
    data = _tracker().parse(_soup(NO_FLIGHT_PAGE), NO_FLIGHT_PAGE)
    assert data["price"] is None
    assert data.get("list_price") is None
    assert data["name"].startswith("Apple AirPods Pro")


NO_UNIT_PRICE = BODY.format(
    ld=JSON_LD,
    flight=r"""
<script>self.__next_f.push([1,"b7:{\"image\":\"https://cdn.mafrservices.com/x/733391_main.jpg\",\"discount\":\"340\",\"price\":\"709.00\",\"currencyISO\":\"SAR\"}\n"])</script>
""",
)


def test_list_price_falls_back_to_price_plus_discount():
    """709 + 340 == 1049, which matched unitPrice exactly on the live
    page — so the sum is a sound second route when unitPrice is out of
    anchoring range."""
    data = _tracker().parse(_soup(NO_UNIT_PRICE), NO_UNIT_PRICE)
    assert data["price"] == "709.00"
    assert Decimal(data["list_price"]) == Decimal("1049.00")


NO_DISCOUNT = BODY.format(
    ld=JSON_LD,
    flight=r"""
<script>self.__next_f.push([1,"c4:{\"image\":\"https://cdn.mafrservices.com/x/733391_main.jpg\",\"currency\":\"SAR\",\"finalPrice\":\"709.00\"}\n"])</script>
""",
)


def test_no_discount_means_no_list_price_not_a_zero():
    data = _tracker().parse(_soup(NO_DISCOUNT), NO_DISCOUNT)
    assert data["price"] == "709.00"
    assert data.get("list_price") is None
    product = CarrefourTracker(LIVE_URL, fetcher=_FakeFetcher(NO_DISCOUNT)).fetch()
    assert product.discount_pct is None


# --------------------------------------------------------------------
# Page-level hole filling
# --------------------------------------------------------------------

NO_JSON_LD_PAGE = """
<html><head>
<title>Buy Apple AirPods Pro 2 Online | Carrefour KSA</title>
<meta property="og:image" content="https://cdn.mafrservices.com/x/733391_main.jpg">
</head><body>
<h1>Apple AirPods Pro 2nd Gen USB-C Earbuds (MTJV3ZEA)</h1>
</body></html>
"""


def test_without_json_ld_name_image_and_sku_still_come_through():
    data = _tracker().parse(_soup(NO_JSON_LD_PAGE), NO_JSON_LD_PAGE)
    assert data["name"] == "Apple AirPods Pro 2nd Gen USB-C Earbuds (MTJV3ZEA)"
    assert data["image"].endswith("733391_main.jpg")
    assert data["sku"] == "733391"


def test_title_is_stripped_of_the_buy_online_wrapper():
    headless = NO_JSON_LD_PAGE.replace(
        "<h1>Apple AirPods Pro 2nd Gen USB-C Earbuds (MTJV3ZEA)</h1>", ""
    )
    data = _tracker().parse(_soup(headless), headless)
    assert data["name"] == "Apple AirPods Pro 2"


def test_title_without_the_wrapper_is_kept_as_is():
    page = """<html><head>
    <meta property="og:title" content="Nescafe Gold Jar 200g | Carrefour KSA">
    </head><body></body></html>"""
    data = _tracker().parse(_soup(page), page)
    assert data["name"] == "Nescafe Gold Jar 200g"


# --------------------------------------------------------------------
# Regressions found on live pages, after the tracker was already passing
# --------------------------------------------------------------------

ENTITY_NAME_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Kenwood Air Fryer HFP52.000BK &ndash; 5 L","sku":"756010",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"390",
           "availability":"https://schema.org/InStock"}}
</script>
</head><body>
<script>self.__next_f.push([1,"b7:{\\"image\\":\\"https://cdn.mafrservices.com/pim-content/SAU/media/product/756010/1/756010_main.jpg\\",\\"discount\\":\\"390\\",\\"price\\":\\"289.00\\",\\"currencyISO\\":\\"SAR\\"}\\n"])</script>
</body></html>
"""

KENWOOD_URL = (
    "https://www.carrefourksa.com/mafsau/en/fryer/"
    "kenwood-airfryer-hfp52-000bk-5l/p/756010"
)


def test_html_entities_in_the_name_are_decoded():
    """Live, SKU 756010: Carrefour ships '&ndash;' as literal characters
    inside the JSON string, so json.loads cannot undo it."""
    data = CarrefourTracker(KENWOOD_URL, fetcher=_FakeFetcher()).parse(
        _soup(ENTITY_NAME_PAGE), ENTITY_NAME_PAGE
    )
    assert data["name"] == "Kenwood Air Fryer HFP52.000BK – 5 L"
    assert "&ndash;" not in data["name"]


def test_the_kenwood_numbers_reproduce():
    """679 - 289 == 390, the figure JSON-LD offered as the price."""
    data = CarrefourTracker(KENWOOD_URL, fetcher=_FakeFetcher()).parse(
        _soup(ENTITY_NAME_PAGE), ENTITY_NAME_PAGE
    )
    assert data["price"] == "289.00"
    assert Decimal(data["list_price"]) == Decimal("679.00")


UNDISCOUNTED_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"PowerN Bluetooth Speaker Watrproof (Pnwiskb)","sku":"765044",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"79.00",
           "availability":"https://schema.org/InStock"}}
</script>
</head><body>
<script>self.__next_f.push([1,"a3:{\\"image\\":\\"https://cdn.mafrservices.com/x/765044_main.jpg\\",\\"unitPrice\\":79,\\"price\\":\\"79.00\\",\\"currencyISO\\":\\"SAR\\"}\\n"])</script>
</body></html>
"""

SPEAKER_URL = (
    "https://www.carrefourksa.com/mafsau/en/bluetooth-speakers/"
    "powern-bt-speaker-watrproof-pnwiskb/p/765044"
)


def test_an_undiscounted_product_reports_no_list_price():
    """Live, SKU 765044: unitPrice == price == 79. That is not an offer,
    so list_price must be absent rather than equal."""
    tracker = CarrefourTracker(SPEAKER_URL, fetcher=_FakeFetcher(UNDISCOUNTED_PAGE))
    data = tracker.parse(_soup(UNDISCOUNTED_PAGE), UNDISCOUNTED_PAGE)
    assert data["price"] == "79.00"
    assert data["list_price"] is None

    product = tracker.fetch()
    assert product.list_price is None
    assert product.discount_pct is None
    assert product.to_dict()["list_price"] is None


def test_json_ld_price_equals_the_real_price_when_undiscounted():
    """The reason offers.price cannot be repaired, only discarded: it is
    the discount when there is one (340, 390, 8.5 live) and the price
    when there is not (79.00 live). Nothing in the block says which."""
    tracker = CarrefourTracker(SPEAKER_URL, fetcher=_FakeFetcher())
    data = tracker.parse(_soup(UNDISCOUNTED_PAGE), UNDISCOUNTED_PAGE)
    assert data["price"] == "79.00"