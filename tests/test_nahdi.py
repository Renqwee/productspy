"""NahdiTracker — offline, but cut from live markup.

Every fixture below is copied out of pages fetched on **2026-08-14**:

    103969818  Momcozy BM01 monitor    735.21 SAR, was  919.01, -20.0%
    104038610  Ninja Creami NC701UK   1699.00 SAR, was 1898.65, -10.5%

Two things about the shape here are load-bearing and are not tidied up:

  - the offer is an **AggregateOffer with no `price` key at all**, only
    lowPrice/highPrice. A fixture carrying `price` would be testing a
    page Nahdi does not serve, and would hide the fact that the selling
    price is reached through the lowPrice branch.
  - `offerCount` is 1 while lowPrice != highPrice. That combination is
    the whole reason the mapping is safe to make, so it stays in the
    fixture rather than being rounded off to a plausible-looking 2.

The headline case is test_low_price_is_what_you_pay, on the **discounted**
products. A full-price page reads the same under either mapping and would
prove nothing.
"""

import pytest
from bs4 import BeautifulSoup

from productspy.registry import resolve_tracker
from productspy.trackers.nahdi import NahdiTracker


URL_MONITOR = "https://www.nahdionline.com/ar-sa/103969818/pdp/103969818"
URL_NINJA = "https://www.nahdionline.com/ar-sa/104038610/pdp/104038610"


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def page(product_json: str) -> str:
    """Nahdi ships five ld+json blocks and Product is the last of them."""
    return f"""<html><head>
      <script type="application/ld+json">{{"@type":"Organization","name":"Nahdi"}}</script>
      <script type="application/ld+json">{{"@type":"BreadcrumbList","itemListElement":[]}}</script>
      <script type="application/ld+json">{{"@type":"WebSite","url":"https://www.nahdionline.com"}}</script>
      <script type="application/ld+json">{{"@type":"ImageObject","url":"https://x/y.jpg"}}</script>
      <script type="application/ld+json">{product_json}</script>
      </head><body></body></html>"""


MONITOR = """{
  "@context": "https://schema.org", "@type": "Product",
  "name": "مومكوزي كاميرا مراقبة الاطفال بشاشة خارجية BM01",
  "sku": "103969818",
  "image": "https://dam.nahdionline.com/x.jpg",
  "offers": {
    "@type": "AggregateOffer",
    "url": "https://www.nahdionline.com/ar-sa/103969818/pdp/103969818",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/NewCondition",
    "priceCurrency": "SAR",
    "lowPrice": 735.21, "highPrice": 919.01, "offerCount": 1,
    "priceValidUntil": "2026-12-31"
  }
}"""

NINJA = """{
  "@context": "https://schema.org", "@type": "Product",
  "name": "نينجا كريمي سكوب آند سويرل NC701UK", "sku": "104038610",
  "offers": {
    "@type": "AggregateOffer", "availability": "https://schema.org/InStock",
    "priceCurrency": "SAR",
    "lowPrice": 1699, "highPrice": 1898.65, "offerCount": 1
  }
}"""

#: صفحة **بلا خصم**، حية 2026-08-14. الشكل يختلف كلياً: `Offer` عادي
#: بـ`price`، لا `AggregateOffer` بحقلين متساويين. ينسخ كما خُدم.
SKINOREN = """{
  "@context": "https://schema.org", "@type": "Product",
  "name": "سكينورين كريم 30 جم", "sku": "100023285",
  "offers": {
    "@type": "Offer",
    "url": "https://www.nahdionline.com/ar-sa/skinoren-cream-30-gm/pdp/100023285",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/NewCondition",
    "priceCurrency": "SAR", "price": 32.7, "priceValidUntil": "2026-12-31"
  }
}"""

URL_SKINOREN = "https://www.nahdionline.com/ar-sa/skinoren-cream-30-gm/pdp/100023285"


# ── التوجيه ───────────────────────────────────────────────────────────────


def test_domain_routes_to_nahdi():
    assert resolve_tracker("nahdionline.com") is NahdiTracker
    assert resolve_tracker("www.nahdionline.com") is NahdiTracker


def test_lookalike_domains_do_not_route_here():
    """المطابقة على حدود التسميات: نطاق شخص آخر ما ياخذ الـ tracker."""
    from productspy.exceptions import UnsupportedSiteError

    for bad in ("fakenahdionline.com", "nahdionline.com.attacker.net"):
        with pytest.raises(UnsupportedSiteError):
            resolve_tracker(bad)


# ── السعر ─────────────────────────────────────────────────────────────────


def test_low_price_is_what_you_pay():
    """المرساة: صفحة **عليها خصم**، والحساب يغلق على المعلن.

    lowPrice = 735.21 وhighPrice = 919.01، والصفحة المرسومة تعرض 735.21
    في خانة السعر و919.01 مشطوباً وشارة «وفر 20 %».
    (919.01 - 735.21) / 919.01 = 20.0% — يطابق الشارة للعُشر.

    وصفحة بلا خصم تقرأ نفس الشيء تحت أي تعيين، فما تثبت شيئاً.
    """
    data = NahdiTracker(URL_MONITOR).parse(soup_of(page(MONITOR)), "")
    assert data["price"] == 735.21
    assert data["list_price"] == 919.01
    assert data["currency"] == "SAR"
    assert data["in_stock"] is True
    assert data["sku"] == "103969818"


def test_there_is_no_price_key_to_fall_back_on():
    """الحارس: لو انكسر فرع lowPrice، ما فيه `price` ينقذ الموقف.

    يوثّق البنية لا يختبر سلوكاً — النهدي ما يشحن `price` إطلاقاً.
    """
    import json

    assert "price" not in json.loads(MONITOR)["offers"]


def test_offer_count_is_kept_because_the_mapping_rests_on_it():
    """lowPrice = سعر البيع صحيح **لأن** العرض واحد.

    لو صار النهدي متعدد البائعين، lowPrice يصير أرخص بائع وينقلب
    التعيين لفخ كارفور. offer_count في raw يخلي ذاك اليوم مرئياً.
    """
    data = NahdiTracker(URL_MONITOR).parse(soup_of(page(MONITOR)), "")
    assert data["offer_count"] == 1


def test_list_price_at_or_below_price_is_dropped():
    """نفس حارس كارفور وجرير: مشطوب ≤ المدفوع ليس عرضاً."""
    same = MONITOR.replace('"highPrice": 919.01', '"highPrice": 735.21')
    data = NahdiTracker(URL_MONITOR).parse(soup_of(page(same)), "")
    assert data["price"] == 735.21
    assert data.get("list_price") is None


def test_undiscounted_page_is_a_plain_offer_with_price():
    """حيّاً على 100023285: بلا خصم يعني **نوع عرض مختلف** لا حقلين متساويين.

    كان المتوقع `AggregateOffer` بـ lowPrice == highPrice، والواقع
    `Offer` عادي بـ `price` وبلا الحقلين إطلاقاً. فالفرعان مساران
    حيّان، لا مسار واحد واحتياط.
    """
    data = NahdiTracker(URL_SKINOREN).parse(soup_of(page(SKINOREN)), "")
    assert data["price"] == 32.7
    assert data["in_stock"] is True
    assert data["sku"] == "100023285"


def test_no_discount_invents_no_list_price():
    """الأهم: صفحة بسعر كامل ما تخترع عرضاً.

    `list_price` None يعني `discount_pct` None — والغائب والصفر معنيان
    مختلفان عند تنبيه سعر.
    """
    data = NahdiTracker(URL_SKINOREN).parse(soup_of(page(SKINOREN)), "")
    assert data.get("list_price") is None


def test_second_product_matches_its_page():
    data = NahdiTracker(URL_NINJA).parse(soup_of(page(NINJA)), "")
    assert data["price"] == 1699
    assert data["list_price"] == 1898.65


def test_product_is_found_past_four_other_blocks():
    """النهدي يشحن خمس كتل ld+json وProduct آخرها."""
    data = NahdiTracker(URL_MONITOR).parse(soup_of(page(MONITOR)), "")
    assert data["name"].startswith("مومكوزي")


# ── الرابط ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,sku,locale",
    [
        (URL_MONITOR, "103969818", "ar-sa"),
        (URL_SKINOREN, "100023285", "ar-sa"),
        ("https://www.nahdionline.com/en-sa/104038610/pdp/104038610",
         "104038610", "en-sa"),
    ],
)
def test_sku_and_locale_come_off_the_path(url, sku, locale):
    data = NahdiTracker(url).parse(soup_of(page(NINJA)), "")
    assert data["locale"] == locale
    assert NahdiTracker(url).url.endswith(f"/{sku}/pdp/{sku}")


def test_slug_and_numeric_links_collapse_to_one_product():
    """المقطع الأوسط مهمَل عند الخادم، فلا يجوز أن يكون مفتاحاً.

    مقيس في الاتجاهين: `/ar-sa/100023285/pdp/100023285` يحوّل لشكل الـ
    slug، و`/ar-sa/any-slug-at-all/pdp/103969818` يحوّل للشكل الرقمي.
    فلو بقي المقطع في المفتاح، وصل نفس الكريم من رابط بحث ومن رابط
    مشارَك كمنتجين، لكل واحد تاريخ سعر وتنبيه مكرر — درس `?o=` عند نون
    بثوب آخر.
    """
    slug = NahdiTracker(URL_SKINOREN).url
    numeric = NahdiTracker(
        "https://www.nahdionline.com/ar-sa/100023285/pdp/100023285").url
    other = NahdiTracker(
        "https://www.nahdionline.com/ar-sa/any-slug-at-all/pdp/100023285").url
    assert slug == numeric == other
    assert slug.endswith("/ar-sa/100023285/pdp/100023285")


def test_query_is_dropped_but_the_locale_prefix_survives():
    """اللغة مسار لا باراميتر، وتُترك عمداً على وزن جرير."""
    messy = URL_SKINOREN + "?utm_source=x&gclid=y"
    assert NahdiTracker(messy).url.endswith("/ar-sa/100023285/pdp/100023285")
    assert "?" not in NahdiTracker(messy).url


def test_an_unrecognisable_url_is_left_alone_rather_than_mangled():
    """ما ينطبق عليه النمط يمر كما هو: التخمين أسوأ من الترك."""
    odd = "https://www.nahdionline.com/ar-sa/static/shipping-delivery"
    assert NahdiTracker(odd).url == odd


def test_english_mirror_is_kept_as_its_own_page():
    """اللغة تبقى، والمقطع الأوسط يسقط — الاثنان في نفس الدالة عمداً."""
    en = "https://www.nahdionline.com/en-sa/skinoren-cream-30-gm/pdp/100023285"
    assert NahdiTracker(en).url.endswith("/en-sa/100023285/pdp/100023285")
    assert NahdiTracker(en).url != NahdiTracker(URL_SKINOREN).url


# ── العملة ────────────────────────────────────────────────────────────────


def test_currency_is_stated_not_derived_from_the_tld():
    """.com كان بيعطي USD عبر الاشتقاق، والمتجر يقتبس بالريال."""
    assert NahdiTracker.default_currency == "SAR"
