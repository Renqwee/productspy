"""ExtraTracker — offline, but cut from live markup.

Every fixture below is copied out of a page fetched on **2026-08-03**:

    100462501  Apple iPhone 17 Pro Max 5G 6.9" 256GB Silver — 5699, no discount
    100389560  Samsung Galaxy A16 4G 128GB 4GB RAM Black    —  549, was 619

The app-state fragments are **verbatim**, including the 570 characters that
separate priceRange from the SKU anchor. That gap is the point: it is what
the lookbehind window is sized against, so a fixture that pushed the two
fields together would test a page that does not exist.

The headline case is test_json_ld_price_is_the_selling_price — the check
Carrefour failed. There offers.price carried the discount amount; here it
carries what the customer pays, and the two pages prove it both ways round.

What is NOT covered here, because it cannot be: the dataLayer fallback has
never run on a real Extra page. Its payloads are JS literals that json.loads
rejects, so the strict-JSON tests at the bottom describe a shape Extra does
not serve. See the ExtraTracker docstring.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from productspy.models import detect_currency
from productspy.registry import resolve_tracker
from productspy.trackers.extra import ExtraTracker


URL_IPHONE = (
    "https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/"
    "apple-iphone-17-pro-max-5g-6-9-inch-256gb-silver/p/100462501"
)
URL_GALAXY = (
    "https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/"
    "samsung-galaxy-a16-4g-128gb-4gb-ram-black/p/100389560"
)


class _FakeResponse:
    status_code = 200

    def __init__(self, html, url):
        self.text = html
        self.url = url


class _FakeFetcher:
    def __init__(self, html=None, url="https://www.extra.com/p"):
        self.html = html
        self.url = url

    def get(self, url, **kwargs):
        return _FakeResponse(self.html or "<html></html>", self.url)


# ── fixtures cut from the live pages, 2026-08-03 ──────────────────────────

# From 100389560. Trimmed only at additionalProperty, which is ~4KB of
# spec rows the tracker never reads; offers is untouched.
JSON_LD_GALAXY = """
<script type="application/ld+json">
{"@id":"#product","@context":"https://schema.org","@type":"Product",
 "brand":{"@type":"Brand","name":"SAMSUNG"},
 "sku":"100389560","mpn":"SM-A165FZKDMEA",
 "url":"https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/samsung-galaxy-a16-4g-128gb-4gb-ram-black/p/100389560",
 "name":"Samsung Galaxy A16, 4G, 128GB, 4GB RAM, Black",
 "image":"https://media.extra.com/s/aurora/100389560_800/Samsung-Galaxy-A16%2C-4G%2C-128GB%2C-4GB-RAM%2C-Black?locale=en-GB,en-*,*&$Listing-Product-2x$",
 "description":"",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"549",
   "itemCondition":"https://schema.org/NewCondition",
   "availability":"https://schema.org/InStock",
   "url":"https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/samsung-galaxy-a16-4g-128gb-4gb-ram-black/p/100389560",
   "seller":{"@type":"Organization","name":"Extra Stores"}}}
</script>
"""

# From 100462501, same trim.
JSON_LD_IPHONE = """
<script type="application/ld+json">
{"@id":"#product","@context":"https://schema.org","@type":"Product",
 "brand":{"@type":"Brand","name":"APPLE"},
 "sku":"100462501","mpn":"MFY84AH/A",
 "url":"https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/apple-iphone-17-pro-max-5g-6-9-inch-256gb-silver/p/100462501",
 "name":"Apple iPhone 17 Pro Max, 5G, 6.9 inch 256GB, Silver",
 "image":"https://media.extra.com/s/aurora/100462501_800/Apple-iPhone-17-Pro-Max%2C-5G%2C-6-9-inch-256GB%2C-Silver?locale=en-GB,en-*,*&$Listing-Product-2x$",
 "description":"",
 "offers":{"@type":"Offer","priceCurrency":"SAR","price":"5699",
   "itemCondition":"https://schema.org/NewCondition",
   "availability":"https://schema.org/InStock",
   "url":"https://www.extra.com/en-sa/mobiles-tablets/mobiles/smartphone/apple-iphone-17-pro-max-5g-6-9-inch-256gb-silver/p/100462501",
   "seller":{"@type":"Organization","name":"Extra Stores"}}}
</script>
"""

# Verbatim, byte for byte, from 100389560. Discounted: discountPrice is the
# 549 you pay, and the plain priceRange is the 619 struck through.
APP_STATE_GALAXY = (
    '"priceRange":{"minPrice":{"currencyIso":"SAR","value":619,"priceType":"FROM"'
    ',"formattedValue":"619","minQuantity":null,"maxQuantity":null,"sapUnit":null}'
    ',"maxPrice":{"currencyIso":"SAR","value":619,"priceType":"FROM","formattedVal'
    'ue":"619","minQuantity":null,"maxQuantity":null,"sapUnit":null}},"firstCatego'
    'ryNameList":null,"multidimensional":true,"configurable":false,"configuratorTy'
    'pe":null,"addToCartDisabled":null,"addToCartDisabledMessage":null,"tags":null'
    ',"sapUnit":{"availabilityCode":"pieces","code":"pieces","name":"Piece"},"keyw'
    'ords":null,"offersSummary":null,"amplienceMediaSet":"100389560_800","discount'
    'Price":{"currencyIso":"SAR","value":549,"priceType":"BUY","formattedValue":"5'
    '49","minQuantity":null,"maxQuantity":null,"sapUnit":null},"percentageDiscount'
    '":{"currencyIso":"SAR","value":11.3,"priceType":"BUY","formattedValue":"11.3"'
    ',"minQuantity":null,"maxQuantity":null,"sapUnit":null},'
)

# Verbatim from 100462501. No discount: discountPrice is null and the plain
# priceRange is the selling price, not a strikethrough.
APP_STATE_IPHONE = (
    '"priceRange":{"minPrice":{"currencyIso":"SAR","value":5699,"priceType":"FROM"'
    ',"formattedValue":"5699","minQuantity":null,"maxQuantity":null,"sapUnit":null}'
    ',"maxPrice":{"currencyIso":"SAR","value":5699,"priceType":"FROM","formattedVa'
    'lue":"5699","minQuantity":null,"maxQuantity":null,"sapUnit":null}},"firstCate'
    'goryNameList":null,"multidimensional":true,"configurable":false,"configurator'
    'Type":null,"addToCartDisabled":null,"addToCartDisabledMessage":null,"tags":nu'
    'll,"sapUnit":{"availabilityCode":"pieces","code":"pieces","name":"Piece"},"ke'
    'ywords":null,"offersSummary":null,"amplienceMediaSet":"100462501_800","discou'
    'ntPrice":null,"percentageDiscount":null,'
)


def page(json_ld, app_state):
    return f"<html><head>{json_ld}</head><body><script>{app_state}</script></body></html>"


GALAXY_PAGE = page(JSON_LD_GALAXY, APP_STATE_GALAXY)
IPHONE_PAGE = page(JSON_LD_IPHONE, APP_STATE_IPHONE)


def run(html, url):
    return ExtraTracker(url, fetcher=_FakeFetcher(html, url)).fetch()


# ── the check Carrefour failed ────────────────────────────────────────────

def test_json_ld_price_is_the_selling_price():
    """549 is what you pay, not the 70 saved and not the 619 before.

    Carrefour puts the discount amount in offers.price, so this cannot be
    assumed for any store — it has to be read off a discounted page and
    compared. On 2026-08-03 this page sold at 549, marked down from 619.
    """
    product = run(GALAXY_PAGE, URL_GALAXY)
    assert product.price == Decimal("549")
    assert product.price != Decimal("70")    # the discount amount
    assert product.price != Decimal("619")   # the pre-discount price
    assert product.raw["price_source"] == "json-ld"


def test_live_values_round_trip():
    galaxy = run(GALAXY_PAGE, URL_GALAXY)
    assert galaxy.name == "Samsung Galaxy A16, 4G, 128GB, 4GB RAM, Black"
    assert galaxy.currency == "SAR"
    assert galaxy.in_stock is True
    assert galaxy.sku == "100389560"
    assert galaxy.image.startswith("https://media.extra.com/s/aurora/100389560_800/")

    iphone = run(IPHONE_PAGE, URL_IPHONE)
    assert iphone.name == "Apple iPhone 17 Pro Max, 5G, 6.9 inch 256GB, Silver"
    assert iphone.price == Decimal("5699")
    assert iphone.currency == "SAR"
    assert iphone.in_stock is True
    assert iphone.sku == "100462501"


# ── list price: not in JSON-LD at all, so it comes from the app state ─────

def test_no_price_specification_anywhere_on_the_page():
    """The shared JSON-LD helper cannot work here, and that is why the
    app-state path exists. Zero priceSpecification on both live pages."""
    assert "priceSpecification" not in GALAXY_PAGE
    soup = BeautifulSoup(GALAXY_PAGE, "html.parser")
    node = ExtraTracker.find_json_ld_product(soup)
    assert ExtraTracker.list_price_from_json_ld(node) is None


def test_strikethrough_comes_from_the_app_state():
    product = run(GALAXY_PAGE, URL_GALAXY)
    assert product.list_price == Decimal("619")
    assert product.raw["list_price_source"] == "app-state priceRange.minPrice"
    # 70 / 619 = 11.3%, which is what percentageDiscount says on the page
    assert round(product.discount_pct, 1) == Decimal("11.3")


def test_no_discount_page_reports_no_list_price():
    """discountPrice is null here, so priceRange is the selling price.

    Read without that test, this page would invent a 5699 strikethrough on
    a product selling at 5699 — a permanent fake offer on every full-price
    listing in the catalogue.
    """
    product = run(IPHONE_PAGE, URL_IPHONE)
    assert product.list_price is None
    assert product.discount_pct is None
    assert "list_price_source" not in product.raw


def test_list_price_is_anchored_to_the_sku():
    """A PDP carries other products' price blocks; the anchor is the SKU.

    Both halves of this document are live markup — the iPhone page has no
    discount and the Galaxy page does, so if the anchor slipped, the 5699
    block is right there to be picked up.
    """
    combined = page(JSON_LD_GALAXY, APP_STATE_IPHONE + APP_STATE_GALAXY)
    product = run(combined, URL_GALAXY)
    assert product.price == Decimal("549")
    assert product.list_price == Decimal("619")


def test_unknown_sku_finds_no_anchor_and_reports_nothing():
    assert ExtraTracker._list_price_from_app_state(
        GALAXY_PAGE, "999999999", "549"
    ) is None


def test_list_price_at_or_below_price_is_dropped():
    """Not an offer. Carrefour needed the same guard: the raw field goes on
    claiming a deal long after discount_pct has correctly gone quiet."""
    assert ExtraTracker._list_price_from_app_state(
        APP_STATE_GALAXY, "100389560", "619"
    ) is None
    assert ExtraTracker._list_price_from_app_state(
        APP_STATE_GALAXY, "100389560", "700"
    ) is None
    assert ExtraTracker._list_price_from_app_state(
        APP_STATE_GALAXY, "100389560", "549"
    ) == "619"


# ── the dataLayer fallback: real payloads, and why it never fires ─────────

# Verbatim from 100389560. Note 'value': 549 next to "price": 619 — the
# selling price and the pre-discount price, both present, differently named.
LIVE_GTM_PUSH = """
<script>
dataLayer.push({
    		'event': 'view_item',
    		'ecommerce': {
    			'currency': 'sar',
    			'value': 549,
          'marketplace_product_flag': pdpDetails.marketPlaceProduct === true ? 'Yes':'No',
    			'items': [{
    				"item_name": "samsung galaxy a16, 4g, 128gb, 4gb ram, black",
    				"item_id": "100389560",
    				"currency": "sar",
    				"discount": 70,
    				"price": 619,
    				"quantity": 1,
    			}]
    		}
    		})
</script>
"""


def test_balanced_object_survives_the_live_payload():
    """The brace scanner is not what breaks on Extra — it cuts correctly."""
    start = LIVE_GTM_PUSH.find("{", LIVE_GTM_PUSH.find("dataLayer.push("))
    blob = ExtraTracker._balanced_object(LIVE_GTM_PUSH, start)
    assert blob is not None
    assert blob.startswith("{")
    assert blob.rstrip().endswith("}")
    assert "'items'" in blob        # it reached past the nested array
    assert "</script>" not in blob  # and stopped before running off the end


def test_live_payload_is_js_not_json_so_the_fallback_yields_nothing():
    """Single-quoted keys and live JS expressions. json.loads refuses, the
    parse is skipped rather than failed, and _from_data_layer returns None.

    This is why the fallback is marked unverified: on the only store it was
    written for, it has never produced a value.
    """
    assert ExtraTracker._from_data_layer(LIVE_GTM_PUSH) is None


# The strict-JSON shape below is constructed, not live. Extra does not
# serve it; it stands in for a store or template that pushes real JSON.
STRICT_GA4_PAGE = """
<html><head>
<script>
dataLayer.push({"event":"view_item","ecommerce":{"currency":"SAR","value":549,
  "items":[{"item_name":"Samsung Galaxy A16","price":619,"discount":70,
            "currency":"SAR"}]}});
</script>
</head><body></body></html>
"""


def test_ga4_fallback_takes_the_value_not_the_item_price():
    """items[].price is the pre-discount unit price in GA4; ecommerce.value
    is what is actually paid. Extra's own push carries 619 and 549 side by
    side, so reading the wrong one inflates the tracked price by 12.7%."""
    item = ExtraTracker._from_data_layer(STRICT_GA4_PAGE)
    assert item["price"] == 549
    assert item["price"] != 619
    assert item["name"] == "Samsung Galaxy A16"
    assert item["currency"] == "SAR"


STRICT_GA3_PAGE = """
<html><head>
<script>
dataLayer.push({"ecommerce":{"currencyCode":"SAR","detail":{"products":[
  {"name":"Blender","price":"349"}]}}});
</script>
</head><body></body></html>
"""


def test_ga3_fallback_still_reads_the_product_price():
    """GA3 has no ecommerce.value and products[].price is the selling price
    by that spec — the GA4 rule must not be applied to it."""
    item = ExtraTracker._from_data_layer(STRICT_GA3_PAGE)
    assert item["price"] == "349"
    assert item["currency"] == "SAR"


def test_fallback_only_fills_holes_it_does_not_override_json_ld():
    combined = GALAXY_PAGE.replace("</head>", STRICT_GA4_PAGE + "</head>")
    product = run(combined, URL_GALAXY)
    assert product.price == Decimal("549")
    assert product.name == "Samsung Galaxy A16, 4G, 128GB, 4GB RAM, Black"


# ── currency ──────────────────────────────────────────────────────────────

def test_new_riyal_glyph_is_recognised():
    """U+20C1 as the page renders it — 100462501 shows it before 5699."""
    assert detect_currency("\u20c15699", "XXX") == "SAR"
    assert detect_currency("\u20c1 549", "XXX") == "SAR"


def test_the_glyph_is_never_actually_served_by_extra():
    """Recorded so nobody credits it for Extra working. The served markup
    says the ASCII string "SAR"; the glyph is drawn client-side, and zero
    copies of it appear in either live page in any encoding."""
    assert "\u20c1" not in GALAXY_PAGE
    assert '"priceCurrency":"SAR"' in GALAXY_PAGE.replace(" ", "")


def test_spelled_out_riyal_is_still_ambiguous_and_left_alone():
    """"ريال" is shared with the Qatari, Omani and Yemeni riyal, and being
    4 characters it would outrank "ر.ق" (3) in the longest-hint ordering —
    a Qatari page would read as SAR. It stays out until that is solved."""
    assert detect_currency("249.00ريال", "XXX") == "XXX"
    assert detect_currency("249.00 ر.ق", "XXX") == "QAR"


# ── routing ───────────────────────────────────────────────────────────────

def test_resolve_tracker_extra():
    assert resolve_tracker("extra.com") is ExtraTracker


@pytest.mark.parametrize("url", [URL_IPHONE, URL_GALAXY])
def test_normalize_url_keeps_the_pdp_path(url):
    assert ExtraTracker(url, fetcher=_FakeFetcher()).url == url
