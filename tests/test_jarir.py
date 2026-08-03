"""JarirTracker — offline, but cut from live markup.

Every fixture below is copied out of pages fetched on **2026-08-03**:

    648717  Asus Zenbook 14        5499 SAR, was 5999   not sold online
    628106  iPhone 15 Pro Max      3199 SAR, was 5699   renewed, in stock
    566474  HP Renew backpack       249 SAR, no discount, in stock

Three things are load-bearing about the shapes here and none of them are
tidied up:

  - the two BreadcrumbList blocks come **before** the Product block, and
    every block is wrapped in "@context"/"@graph". A fixture with the
    Product first would not be testing the page Jarir serves.
  - the app-state script does not end at the object. A self-removing IIFE
    follows the closing brace, which is exactly why json.loads fails on
    the script body and raw_decode does not.
  - `stock.stock_status` is 0 on every product, in stock or not. It is
    kept in the in-stock fixtures on purpose: the test that matters is
    that a selling product still reads in_stock=True with that 0 sitting
    right there.

The headline case is test_offers_price_is_the_selling_price, on the two
**discounted** products. An undiscounted page agrees under every reading
of offers.price and would prove nothing — Carrefour's trap (the discount
amount) and Extra's (the pre-discount price) are only ruled out by a page
where the three numbers differ.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from productspy.registry import resolve_tracker
from productspy.trackers.jarir import JarirTracker


URL_ZENBOOK = "https://www.jarir.com/asus-zenbook-14-laptops-648717.html"
URL_IPHONE = (
    "https://www.jarir.com/apple-iphone-15-pro-max-renewed-smartphones-628106.html"
)
URL_BACKPACK = "https://www.jarir.com/hp-cases-and-bags-566474.html"
URL_IPHONE_EN = (
    "https://www.jarir.com/sa-en/"
    "apple-iphone-15-pro-max-renewed-smartphones-628106.html"
)


# --- fixture builders ------------------------------------------------
#
# Verbatim block order: BreadcrumbList, BreadcrumbList, Product.

_BREADCRUMB = """
<script type="application/ld+json" id="metatags">
{
  "@context": "https://schema.org/",
  "@graph": [
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1,
         "item": {"@id": "https://www.jarir.com/", "name": "الرئيسية"}}
      ]
    }
  ]
}
</script>
"""


def product_block(sku, name, price, availability, image):
    return f"""
<script type="application/ld+json" id="metatags">
{{
  "@context": "https://schema.org/",
  "@graph": [
    {{
      "@type": "Product",
      "name": "{name}",
      "sku": "{sku}",
      "description": " وصف",
      "model": "زينبوك 14",
      "image": "{image}",
      "category": "الكمبيوتر والتابلت",
      "url": "https://www.jarir.com/x-{sku}.html",
      "itemCondition": "https://schema.org/NewCondition",
      "brand": {{"@type": "Brand", "name": "Asus"}},
      "offers": {{
        "@type": "Offer",
        "url": "https://www.jarir.com/x-{sku}.html",
        "priceCurrency": "SAR",
        "price": "{price}",
        "availability": "https://schema.org/{availability}",
        "priceValidUntil": "2026-08-04"
      }}
    }}
  ]
}}
</script>
"""


def state_block(sku, mpn, regular, final, promotion, is_stock, showrooms, name):
    """One <script> holding window.__INITIAL_STATE__, IIFE tail included.

    The trailing `;(function(){...}());` is verbatim from the live pages.
    Drop it and json.loads on the script body starts working, and the test
    stops covering the reason raw_decode is used at all.
    """
    return (
        "<script>window.__INITIAL_STATE__={"
        '"version":"","checkout":{"order":{}},'
        '"product":{"current":{'
        f'"sku":"{sku}","mpn":"{mpn}","name":"{name}",'
        f'"regular_price":{regular},"price":{regular},'
        f'"final_price":{final},"special_price":{final},'
        f'"promotion_value":{promotion},"GTM_product_save":{promotion},'
        f'"is_stock_available":{is_stock},"klevu_stock_flag":{is_stock},'
        f'"available_shr":{showrooms},'
        '"stock":{"manage_stock":true,"stock_status":0,"is_in_stock":false},'
        '"type_id":"simple","status":1'
        "},"
        '"original":{"sku":"' + sku + '"}},'
        '"review":{"items":[]},"homepage":{"new_collection":null}};'
        "(function(){var s;(s=document.currentScript||document.scripts"
        "[document.scripts.length-1]).parentNode.removeChild(s);}());"
        "</script>"
    )


def page(product_html, state_html=""):
    return (
        "<html lang='ar' dir='rtl'><head>"
        + _BREADCRUMB
        + _BREADCRUMB
        + product_html
        + "</head><body><h1>عنوان</h1>"
        + state_html
        + "</body></html>"
    )


ZENBOOK = page(
    product_block(
        "648717",
        "اسوس زينبوك 14 لابتوب",
        "5499.00",
        "OutOfStock",
        "https://ak-asset.jarir.com/akeneo-prod/asset/c/6/2/6/c62642_648717.jpg",
    ),
    state_block(
        "648717", "UX3405CAP060W", 5999, 5499, 500, 0, "[]",
        "اسوس زينبوك 14 لابتوب، الذكاء الاصطناعي، 14 بوصة",
    ),
)

IPHONE = page(
    product_block(
        "628106",
        "منتج مجدد درجة ب ابل آيفون 15 برو ماكس",
        "3199.00",
        "InStock",
        "https://ak-asset.jarir.com/akeneo-prod/asset/4/8/1/f/481f96_628106.jpg",
    ),
    state_block(
        "628106", "MU6R3AHARB", 5699, 3199, 2500, 1, '["0155"]',
        "منتج مجدد درجة ب ابل آيفون 15 برو ماكس، 256 جيجابايت",
    ),
)

BACKPACK = page(
    product_block(
        "566474",
        "اتش  بي رينيو حقيبة ظهر",
        "249.00",
        "InStock",
        "https://ak-asset.jarir.com/akeneo-prod/asset/m1/delta/566474.jpg",
    ),
    state_block(
        "566474", "2Z8A3AAABB", 249, 249, "null", 1, '["0307","0314","0309"]',
        "اتش  بي رينيو حقيبة ظهر، مناسب لاجهزة 15.6 بوصة",
    ),
)


def parse(url, html):
    tracker = JarirTracker.__new__(JarirTracker)
    tracker.url = url
    return tracker.parse(BeautifulSoup(html, "html.parser"), html)


@pytest.fixture
def zenbook():
    return parse(URL_ZENBOOK, ZENBOOK)


@pytest.fixture
def iphone():
    return parse(URL_IPHONE, IPHONE)


@pytest.fixture
def backpack():
    return parse(URL_BACKPACK, BACKPACK)


# --- routing ----------------------------------------------------------


def test_registered_on_jarir_com():
    assert resolve_tracker("jarir.com") is JarirTracker
    assert resolve_tracker("www.jarir.com") is JarirTracker


def test_lookalike_domains_do_not_route_here():
    """Label-boundary matching, same rule the other stores get."""
    from productspy.exceptions import UnsupportedSiteError

    for domain in ("fakejarir.com", "jarir.com.attacker.net", "myjarir.com"):
        with pytest.raises(UnsupportedSiteError):
            resolve_tracker(domain)


def test_currency_is_pinned_not_derived():
    """jarir.com is a .com; currency_from_domain would say USD."""
    from productspy.utils.url_tools import currency_from_domain

    assert currency_from_domain("jarir.com") == "USD"
    assert JarirTracker.default_currency == "SAR"


# --- the price trap ---------------------------------------------------


def test_offers_price_is_the_selling_price(zenbook, iphone):
    """The check Carrefour failed and Extra passed, on discounted pages.

    5499 is what you pay; 5999 is the strikethrough and 500 is the saving.
    A tracker reading offers.price as the discount amount (Carrefour) or
    as the pre-discount price (Extra) lands on 500 or 5999 instead.
    """
    assert Decimal(str(zenbook["price"])) == Decimal("5499.00")
    assert Decimal(str(iphone["price"])) == Decimal("3199.00")
    assert zenbook["price_source"] == "json-ld"


def test_list_price_comes_from_the_app_state(zenbook, iphone):
    assert Decimal(str(zenbook["list_price"])) == Decimal("5999")
    assert Decimal(str(iphone["list_price"])) == Decimal("5699")
    assert (
        zenbook["list_price_source"]
        == "app-state product.current.regular_price"
    )


def test_discounts_match_the_page(zenbook, iphone):
    """8% and 43% as advertised; the exact figures are 8.33 and 43.87."""
    from productspy.models import Product

    for data, expected in ((zenbook, "8.3"), (iphone, "43.9")):
        product = Product(
            name=data["name"],
            price=Decimal(str(data["price"])),
            currency="SAR",
            url="x",
            site="Jarir",
            list_price=Decimal(str(data["list_price"])),
        )
        assert product.discount_pct == Decimal(expected)


def test_no_price_specification_anywhere():
    """list_price_from_json_ld returns None by construction here.

    Zero occurrences of priceSpecification on any live page, which is why
    the app-state path is not an optional extra.
    """
    assert "priceSpecification" not in ZENBOOK
    soup = BeautifulSoup(ZENBOOK, "html.parser")
    node = JarirTracker.find_json_ld_product(soup)
    assert JarirTracker.list_price_from_json_ld(node) is None


def test_undiscounted_product_reports_no_list_price(backpack):
    """regular_price == final_price == 249 is not an offer.

    Without the guard the raw field reports "was 249, now 249" forever.
    """
    assert backpack["list_price"] is None
    assert "list_price_source" not in backpack


# --- the two identifiers ----------------------------------------------


def test_sku_is_the_numeric_item_number(zenbook, iphone, backpack):
    """رقم الصنف, the one the page marks itemprop="sku" and the URL carries."""
    assert zenbook["sku"] == "648717"
    assert iphone["sku"] == "628106"
    assert backpack["sku"] == "566474"


def test_manufacturer_code_rides_in_raw_not_in_sku(zenbook, backpack):
    """رقم المنتج is `mpn` in the app state and appears in no URL."""
    assert zenbook["mpn"] == "UX3405CAP060W"
    assert backpack["mpn"] == "2Z8A3AAABB"
    assert zenbook["sku"] != zenbook["mpn"]


def test_sku_from_url_survives_digits_in_the_slug():
    """In "zenbook-14-laptops-648717" the 14 must not win."""
    assert JarirTracker._sku_from_url(URL_ZENBOOK) == "648717"
    assert JarirTracker._sku_from_url(URL_IPHONE_EN) == "628106"
    assert JarirTracker._sku_from_url("https://www.jarir.com/") is None


# --- availability ------------------------------------------------------


def test_not_sold_online_reads_as_out_of_stock(zenbook):
    """648717: "غير متوفّر أونلاين، الرجاء التحقّق من التوفر في المعارض".

    in_stock=False is the store's own reading — schema.org/OutOfStock plus
    is_stock_available=0 — not an inference from the wording. Distinct
    from Amazon's location_blocked, where the item IS sold and only the
    delivery address was refused; there is no location involved here.
    """
    assert zenbook["in_stock"] is False
    assert zenbook["online_stock"] is False
    assert zenbook["in_stock_source"] == "json-ld availability"


def test_check_the_showrooms_is_not_a_stock_signal(zenbook):
    """The page tells you to check the showrooms; none of them have it."""
    assert zenbook["showroom_codes"] == []
    assert zenbook["in_showroom"] is False


def test_delivery_only_product_is_in_stock(iphone):
    """628106: pickup unavailable at the visitor's branch, delivery is on.

    One showroom holds it, so pickup being off is about *which* branch,
    not about stock. in_stock tracks online purchasability.
    """
    assert iphone["in_stock"] is True
    assert iphone["in_showroom"] is True
    assert iphone["showroom_codes"] == ["0155"]


def test_stock_status_zero_does_not_leak_into_in_stock(iphone, backpack):
    """`stock.stock_status` is 0 on every product Jarir serves.

    Both fixtures carry that 0 verbatim. A tracker that read it would call
    every product out of stock and never say why.
    """
    assert '"stock_status":0' in IPHONE
    assert '"is_in_stock":false' in BACKPACK
    assert iphone["in_stock"] is True
    assert backpack["in_stock"] is True


# --- app-state extraction ---------------------------------------------


def test_state_survives_the_trailing_iife():
    """json.loads on the script body fails; raw_decode stops at the brace."""
    import json

    body = ZENBOOK.split("window.__INITIAL_STATE__=", 1)[1].split("</script>")[0]
    with pytest.raises(json.JSONDecodeError):
        json.loads(body.rstrip(";"))

    current = JarirTracker._state_product(ZENBOOK)
    assert current["sku"] == "648717"
    assert current["regular_price"] == 5999


def test_state_for_another_product_is_refused():
    """Identity check, not a proximity window.

    If the blob at product.current belongs to a different item number, it
    is not a source for this page — dropping the list price beats
    recording someone else's.
    """
    mismatched = page(
        product_block(
            "648717", "اسوس", "5499.00", "OutOfStock", "https://x/648717.jpg"
        ),
        state_block(
            "999999", "OTHER", 9999, 8888, 1111, 1, "[]", "منتج آخر"
        ),
    )
    data = parse(URL_ZENBOOK, mismatched)
    assert Decimal(str(data["price"])) == Decimal("5499.00")
    assert data["list_price"] is None
    assert "mpn" not in data


def test_page_without_app_state_still_yields_a_price():
    """JSON-LD alone carries name, price, currency, stock, image and sku."""
    data = parse(
        URL_BACKPACK,
        page(
            product_block(
                "566474",
                "اتش  بي رينيو حقيبة ظهر",
                "249.00",
                "InStock",
                "https://ak-asset.jarir.com/akeneo-prod/asset/m1/delta/566474.jpg",
            )
        ),
    )
    assert Decimal(str(data["price"])) == Decimal("249.00")
    assert data["currency"] == "SAR"
    assert data["in_stock"] is True
    assert data["list_price"] is None


def test_app_state_fills_in_when_json_ld_is_missing():
    """final_price is the selling price there — it agreed with offers.price
    on all five live pages, which is what makes it usable as a fallback."""
    data = parse(
        URL_IPHONE,
        page(
            "",
            state_block(
                "628106", "MU6R3AHARB", 5699, 3199, 2500, 1, '["0155"]',
                "منتج مجدد درجة ب ابل آيفون 15 برو ماكس، 256 جيجابايت",
            ),
        ),
    )
    assert Decimal(str(data["price"])) == Decimal("3199")
    assert data["price_source"] == "app-state product.current.final_price"
    assert Decimal(str(data["list_price"])) == Decimal("5699")
    assert data["in_stock"] is True
    assert data["in_stock_source"] == "app-state is_stock_available"


def test_broken_state_blob_is_not_fatal():
    """A truncated assignment costs the list price, not the fetch."""
    broken = page(
        product_block(
            "566474", "حقيبة", "249.00", "InStock", "https://x/566474.jpg"
        ),
        '<script>window.__INITIAL_STATE__={"product":{"current":{"sku":</script>',
    )
    data = parse(URL_BACKPACK, broken)
    assert Decimal(str(data["price"])) == Decimal("249.00")
    assert data["list_price"] is None


# --- URL handling ------------------------------------------------------


def test_query_string_is_dropped():
    tracker = JarirTracker.__new__(JarirTracker)
    assert (
        tracker.normalize_url(URL_ZENBOOK + "?utm_source=x&gclid=y")
        == URL_ZENBOOK
    )


def test_language_prefix_is_kept():
    """/sa-en/ is a language mirror the store declares self-canonical.

    Same item number, same numbers, different name language — measured on
    648717 and 628106. Collapsing it would silently flip the tracked name
    to Arabic for a caller who pasted the English link.
    """
    tracker = JarirTracker.__new__(JarirTracker)
    assert tracker.normalize_url(URL_IPHONE_EN) == URL_IPHONE_EN
    assert "/sa-en/" in tracker.normalize_url(URL_IPHONE_EN + "?utm_source=x")
