"""LuluTracker — offline, but cut from live markup.

Fixtures copied out of pages fetched on **2026-08-14**:

    2048258 en-sa  Nesquik cereal 330g   23.99 SAR, was 27.95, -14.2%
    2048258 en-ae  the same item         20.50 AED, no discount
      39478 en-sa  Kellogg's Corn Flakes 39.95 SAR, no discount
    2677573 en-sa  Insta360 TV Mount     no price, Out of Stock

Four things about these shapes are load-bearing and none are tidied up:

  - prices keep their **three decimal places** ("23.990"). Rounding a
    fixture to 23.99 would delete the bug the file exists to prevent.
  - the payload run is written **escaped**, the way it arrives inside the
    RSC string literal. Un-escaping it would make the pattern look
    correct while the live page went unmatched.
  - `currency_type` is a bare `null` in the out-of-stock fixture and a
    quoted string in the others. Both arms are live.
  - every fixture declares `schema.org/InStock`, **including the
    out-of-stock one**, because that is exactly what Lulu serves.
"""

import pytest
from bs4 import BeautifulSoup

from productspy.registry import resolve_tracker
from productspy.trackers.lulu import LuluTracker


URL_SA = ("https://gcc.luluhypermarket.com/en-sa/"
          "nestle-nesquik-chocolate-breakfast-cereal-pack-330-g/p/2048258/")
URL_AE = ("https://gcc.luluhypermarket.com/en-ae/"
          "nestle-nesquik-chocolate-breakfast-cereal-pack-330-g/p/2048258/")
URL_PLAIN = "https://gcc.luluhypermarket.com/en-sa/kellogg-s-corn-flakes-the-original-750-g/p/39478/"
URL_OOS = "https://gcc.luluhypermarket.com/en-sa/insta360-connect-tv-mount/p/2677573/"


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def page(name, sku, price, currency, payload_run) -> str:
    """A Product block that always claims InStock, plus the escaped run."""
    cur = "null" if currency is None else f'"{currency}"'
    return f"""<html><head>
      <script type="application/ld+json">{{"@type":"WebSite"}}</script>
      <script type="application/ld+json">{{
        "@context":"https://schema.org","@type":"Product",
        "name":"{name}","sku":"{sku}",
        "offers":{{"@type":"Offer","priceCurrency":{cur},"price":"{price}",
          "availability":"https://schema.org/InStock",
          "itemCondition":"https://schema.org/NewCondition"}}
      }}</script>
      <script type="application/ld+json">{{"@type":"BreadcrumbList"}}</script>
      </head><body><script>self.__next_f.push([1,"{payload_run}"])</script>
      </body></html>"""


#: كما تصل على السلك: كل علامة تنصيص مهروبة داخل حرفية JS.
RUN_SA = (r'\"base_code\":\"2048258\",\"price\":\"23.990\",\"in_stock\":true,'
          r'\"currency_type\":\"sar\",\"retail_price\":\"27.950\",\"unit_type\":\"qty\"')
RUN_AE = (r'\"base_code\":\"2048258\",\"price\":\"20.500\",\"in_stock\":true,'
          r'\"currency_type\":\"aed\",\"retail_price\":\"20.500\",\"unit_type\":\"qty\"')
RUN_PLAIN = (r'\"base_code\":\"39478\",\"price\":\"39.950\",\"in_stock\":true,'
             r'\"currency_type\":\"sar\",\"retail_price\":\"39.950\",\"unit_type\":\"qty\"')
RUN_OOS = (r'\"base_code\":\"2677573\",\"price\":\"0.00\",\"in_stock\":false,'
           r'\"currency_type\":null,\"retail_price\":\"0.00\",\"unit_type\":\"qty\"')

PAGE_SA = page("Nestle Nesquik Chocolate Breakfast Cereal Pack 330 g",
               "2048258", "23.990", "sar", RUN_SA)
PAGE_AE = page("Nestle Nesquik Chocolate Breakfast Cereal Pack 330 g",
               "2048258", "20.500", "aed", RUN_AE)
PAGE_PLAIN = page("Kellogg's Corn Flakes The Original 750 g",
                  "39478", "39.950", "sar", RUN_PLAIN)
PAGE_OOS = page("Insta360 Connect TV Mount", "2677573", "0.00", None, RUN_OOS)


# ── التوجيه ───────────────────────────────────────────────────────────────


def test_domain_routes_to_lulu():
    assert resolve_tracker("gcc.luluhypermarket.com") is LuluTracker
    assert resolve_tracker("www.luluhypermarket.com") is LuluTracker


def test_lookalike_domains_do_not_route_here():
    from productspy.exceptions import UnsupportedSiteError

    for bad in ("fakeluluhypermarket.com", "luluhypermarket.com.attacker.net"):
        with pytest.raises(UnsupportedSiteError):
            resolve_tracker(bad)


# ── الفخ الأول: ثلاث خانات عشرية ──────────────────────────────────────────


def test_three_decimal_price_is_not_read_as_thousands():
    """الفخ القاتل: "23.990" ليست ثلاثاً وعشرين ألفاً.

    `parse_price` تقرأ ذيلاً من ثلاثة أرقام كتجميع — **وهي محقة**
    بمعزل عن السياق، لأن 1.250 أوروبياً ألف ومئتان وخمسون. لولو منصة
    خليجية موحدة، والدينار الكويتي والبحريني بثلاث خانات فعلاً، فتنسّق
    كل الأسواق كذلك. فالغموض يُحل هنا حيث تُعرف هوية المصدر.
    """
    data = LuluTracker(URL_SA).parse(soup_of(PAGE_SA), PAGE_SA)
    assert str(data["price"]) == "23.990"
    assert data["price"] < 100          # لا 23990


def test_the_trap_is_real_in_the_generic_parser():
    """توثيق: لولا التحويل هنا، لكان الرقم أكبر ألف مرة."""
    from productspy.models import parse_price

    assert parse_price("20.000") == 20000


# ── الفخ الثاني: schema.org يكذب في التوفر ────────────────────────────────


def test_out_of_stock_page_declares_instock_and_is_not_believed():
    """حيّاً على 2677573: الصفحة ترسم «Out of Stock» وJSON-LD يقول InStock.

    فالحمولة هي المصدر، وقراءة schema.org هنا تجعل الكتالوج كله
    متوفراً للأبد — فخ `stock_status` عند جرير مقلوباً.
    """
    import json

    ld = json.loads(re_ld(PAGE_OOS))
    assert ld["offers"]["availability"].endswith("InStock")   # هذا ما يُخدم

    data = LuluTracker(URL_OOS).parse(soup_of(PAGE_OOS), PAGE_OOS)
    assert data["in_stock"] is False
    assert data["in_stock_source"] == "payload"


def re_ld(html: str) -> str:
    """أول كتلة Product في الصفحة."""
    import re

    for b in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S):
        if '"Product"' in b:
            return b.strip()
    raise AssertionError("ما فيه كتلة Product")


def test_in_stock_still_reads_true_when_it_should():
    data = LuluTracker(URL_SA).parse(soup_of(PAGE_SA), PAGE_SA)
    assert data["in_stock"] is True


# ── الفخ الثالث: سعر الصفر ────────────────────────────────────────────────


def test_zero_price_is_dropped_not_stored():
    """0.00 على صفحة نافدة قيمة نائبة لا صنف مجاني.

    و`parse_price` مبنية عمداً على **عدم** بلع الصفر المشروع، و`base.py`
    يفحص `is None` للسبب نفسه — فبلا هذا الحارس يمر الصفر كسعر حقيقي،
    وهبوط صنف متتبَّع إلى الصفر أعلى تنبيه خصم كاذب ممكن.
    """
    data = LuluTracker(URL_OOS).parse(soup_of(PAGE_OOS), PAGE_OOS)
    assert data["price"] is None
    assert data["zero_price_dropped"] is True


# ── العملة تتبع المسار ────────────────────────────────────────────────────


def test_currency_follows_the_path_not_the_domain():
    """نفس الصنف، مساران، عملتان وسعران — والنطاق واحد.

    فالعملة لا تصلح صفة صنف ثابتة كما في بقية المتاجر.
    """
    sa = LuluTracker(URL_SA).parse(soup_of(PAGE_SA), PAGE_SA)
    ae = LuluTracker(URL_AE).parse(soup_of(PAGE_AE), PAGE_AE)
    assert (sa["currency"], str(sa["price"])) == ("SAR", "23.990")
    assert (ae["currency"], str(ae["price"])) == ("AED", "20.500")


def test_currency_is_uppercased():
    """الصفحة تكتبها 'sar'، والمشروع كله يخزّن ISO-4217 بحروف كبيرة."""
    data = LuluTracker(URL_SA).parse(soup_of(PAGE_SA), PAGE_SA)
    assert data["currency"] == "SAR"


def test_currency_falls_back_to_the_locale_when_the_page_says_null():
    """الصفحة النافدة ترجّع priceCurrency=null، والمسار يسدّ الثقب."""
    data = LuluTracker(URL_OOS).parse(soup_of(PAGE_OOS), PAGE_OOS)
    assert data["currency"] == "SAR"


# ── المشطوب ───────────────────────────────────────────────────────────────


def test_retail_price_becomes_list_price_when_it_is_higher():
    data = LuluTracker(URL_SA).parse(soup_of(PAGE_SA), PAGE_SA)
    assert str(data["list_price"]) == "27.950"


def test_equal_retail_price_is_not_a_discount():
    """شكل «بلا خصم» عند لولو: retail_price == price، مقيس على أربع صفحات."""
    data = LuluTracker(URL_PLAIN).parse(soup_of(PAGE_PLAIN), PAGE_PLAIN)
    assert str(data["price"]) == "39.950"
    assert data.get("list_price") is None


# ── الحمولة المهروبة ──────────────────────────────────────────────────────


def test_pattern_matches_the_escaped_shape_on_the_wire():
    """الحمولة تعيش داخل حرفية JS، فكل تنصيص مسبوق بشرطة عكسية.

    ونمط مكتوب على الشكل المنمَّق يفشل **صامتاً**: السعر يجي من JSON-LD
    على أي حال، فالخسارة هي المشطوب وعلم التوفر وحدهما.
    """
    from productspy.trackers.lulu import _PAYLOAD

    assert _PAYLOAD.search(RUN_SA) is not None
    unescaped = RUN_SA.replace('\\"', '"')
    assert _PAYLOAD.search(unescaped) is not None


# ── الرابط ────────────────────────────────────────────────────────────────


def test_query_is_dropped():
    assert LuluTracker(URL_SA + "?utm_source=x").url == URL_SA


def test_slug_is_kept_because_the_server_needs_it():
    """عكس النهدي: `/en-sa/x/p/2048258/` يرجّع 404، فالـ slug هوية لا زينة."""
    assert LuluTracker(URL_SA).url == URL_SA
    assert "nestle-nesquik" in LuluTracker(URL_SA).url


def test_locale_is_read_off_the_path():
    assert LuluTracker(URL_SA).locale == "en-sa"
    assert LuluTracker(URL_AE).locale == "en-ae"


def test_url_without_a_locale_is_left_alone_rather_than_given_one():
    """ما نخترع دولة: الخادم يختار، واختراعنا يعيد توجيه رابط سوق آخر."""
    bare = "https://gcc.luluhypermarket.com/nestle-nesquik-cereal/p/2048258/"
    tracker = LuluTracker(bare)
    assert tracker.url == bare
    assert tracker.locale is None
