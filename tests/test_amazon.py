"""اختبارات أمازون — offline بالكامل، ولا واحد منها يلمس الشبكة.

كل fixture هنا مبني ليطابق بنية شوهدت على صفحة حية في 2026-08-01،
والقيم أرقام حقيقية من تلك الصفحات. مصدر كل واحد مكتوب فوقه.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from productspy.models import parse_price
from productspy.trackers.amazon import (
    AmazonTracker,
    _availability,
    _find_price_blocks,
    _price_from_block,
    _tld_suffix,
)

# ── لبنات fixture ──────────────────────────────────────────────────────────


def a_price(symbol, whole, sep, fraction, *, offscreen=None, strike=False):
    """كتلة a-price بنفس بنية أمازون: نسخة offscreen ونسخة aria-hidden.

    التكرار مقصود — هو سبب مشكلة الرقم المضاعف، فلازم يكون في الـ fixture
    وإلا اختبرنا صفحة غير موجودة.
    """
    off = "" if offscreen is None else offscreen
    st = ' data-a-strike="true"' if strike else ""
    return f"""
    <span class="a-price"{st} data-a-size="xl">
      <span class="a-offscreen">{off}</span>
      <span aria-hidden="true"><span class="a-price-symbol">{symbol}</span><span
        class="a-price-whole">{whole}<span class="a-price-decimal">{sep}</span></span><span
        class="a-price-fraction">{fraction}</span></span>
    </span>"""


def page(core_html, *, title="Test Product", extra=""):
    return f"""<html lang="en-ae"><head><title>t</title></head><body>
    <div id="dp-container"><div id="ppd"><div id="centerCol">
      <span id="productTitle">{title}</span>
      <div id="apex_desktop">
        <div id="corePriceDisplay_desktop_feature_div">{core_html}</div>
      </div>
      {extra}
    </div></div></div></body></html>"""


def soup_of(html):
    return BeautifulSoup(html, "html.parser")


SA_URL = "https://www.amazon.sa/dp/B0FWXZLD6F"
DE_URL = "https://www.amazon.de/dp/B09WVVZQD3"
UK_URL = "https://www.amazon.co.uk/dp/B07TCB5DBG"


# ── استخراج السعر ─────────────────────────────────────────────────────────


def test_offscreen_empty_falls_back_to_whole_and_fraction():
    """السعودية حياً: a-offscreen فاضي داخل الحاوية الأساسية.

    لو رجّعت الدالة '' أو None هنا فالمكتبة عمياء على أمازون كله،
    لأن هالحالة هي الافتراضية لا الاستثناء.
    """
    html = page(a_price("SAR", "1,349", ".", "10", offscreen=""))
    _, pay, _ = _find_price_blocks(soup_of(html))
    text, source = _price_from_block(pay)
    assert source == "whole+frac"
    assert parse_price(text) == Decimal("1349.10")


def test_offscreen_used_when_populated():
    """corePrice_feature_div ترجّع offscreen معبّأ على نفس الصفحة."""
    html = page(a_price("SAR", "1,349", ".", "10", offscreen="SAR 1,349.10"))
    _, pay, _ = _find_price_blocks(soup_of(html))
    text, source = _price_from_block(pay)
    assert source == "offscreen"
    assert parse_price(text) == Decimal("1349.10")


def test_naive_get_text_would_double_the_number():
    """توثيق الفخ نفسه: get_text() على الكتلة يجمع النسختين.

    لو انكسر هذا الاختبار يوماً فمعناه أمازون شال التكرار، وساعتها
    نقدر نبسّط _price_from_block. هو اختبار للواقع لا للكود.
    """
    html = page(a_price("SAR", "1,349", ".", "10", offscreen="SAR 1,349.10"))
    _, pay, _ = _find_price_blocks(soup_of(html))
    assert pay.get_text(strip=True) == "SAR 1,349.10SAR1,349.10"


def test_european_separators_from_dom_not_from_currency():
    """ألمانيا بالكوكيز: €314,89.

    الفاصلة تجي من a-price-decimal. لو ثبّتناها '.' لطلع 314.89 صدفةً
    صحيحاً هنا، فالاختبار التالي هو اللي يكشف الفرق فعلاً.
    """
    html = page(a_price("€", "314", ",", "89", offscreen=""))
    _, pay, _ = _find_price_blocks(soup_of(html))
    text, _ = _price_from_block(pay)
    assert text == "€ 314,89"
    assert parse_price(text) == Decimal("314.89")


def test_saudi_currency_with_european_separators():
    """الحالة اللي تكسر أي افتراض يربط العملة بالتنسيق.

    amazon.de بترويسة de-DE وبلا كوكي عملة رجّع حرفياً:
    symbol='SAR' whole='1.363,' decimal=',' fraction='86'
    عملة سعودية بفاصلة أوروبية. تثبيت '.' كفاصلة يعطي 1.363
    أي أقل من الحقيقة بألف ضعف، وبصمت تام.
    """
    html = page(a_price("SAR", "1.363", ",", "86", offscreen=""))
    _, pay, _ = _find_price_blocks(soup_of(html))
    text, _ = _price_from_block(pay)
    assert text == "SAR 1.363,86"
    assert parse_price(text) == Decimal("1363.86")


def test_trailing_separator_is_stripped_from_whole():
    """a-price-decimal مدفون جوّا a-price-whole فنصه يجي '1,349.'."""
    html = page(a_price("SAR", "1,349", ".", "10", offscreen=""))
    _, pay, _ = _find_price_blocks(soup_of(html))
    assert "1,349.." not in _price_from_block(pay)[0]


def test_nbsp_inside_offscreen_is_cleaned():
    """كتل tp_price ترجّع 'SAR\\xa01,349.10' بمسافة غير كاسرة."""
    html = page(a_price("SAR", "1,349", ".", "10", offscreen="SAR\xa01,349.10"))
    _, pay, _ = _find_price_blocks(soup_of(html))
    text, _ = _price_from_block(pay)
    assert "\xa0" not in text
    assert parse_price(text) == Decimal("1349.10")


# ── السعر المشطوب ─────────────────────────────────────────────────────────


def test_list_price_from_struck_block():
    """كرسي السعودية: 1,499.00 مشطوب و1,349.10 حالي = خصم 10% معلن."""
    html = page(
        a_price("SAR", "1,349", ".", "10", offscreen="")
        + a_price("SAR", "1,499", ".", "00", offscreen="SAR1,499.00", strike=True)
    )
    tracker = AmazonTracker(SA_URL)
    data = tracker.parse(soup_of(html), html)
    assert parse_price(data["price"]) == Decimal("1349.10")
    assert parse_price(data["list_price"]) == Decimal("1499.00")


def test_list_price_equal_to_price_is_dropped():
    """list_price == price ليس عرضاً — يُرمى لا يُخزَّن كصفر خصم."""
    same = "SAR 99.00"
    html = page(
        a_price("SAR", "99", ".", "00", offscreen=same)
        + a_price("SAR", "99", ".", "00", offscreen=same, strike=True)
    )
    data = AmazonTracker(SA_URL).parse(soup_of(html), html)
    assert data.get("list_price") is None


def test_struck_block_is_not_mistaken_for_the_price():
    """التمييز على data-a-strike لا على اسم الصنف.

    نفس الصفحة الحية فيها apex-basisprice-value و apex-basis-price-value
    بتهجئتين مختلفتين، فالصنف غير موثوق.
    """
    html = page(
        a_price("SAR", "1,349", ".", "10", offscreen="")
        + a_price("SAR", "1,499", ".", "00", offscreen="", strike=True)
    )
    _, pay, struck = _find_price_blocks(soup_of(html))
    assert parse_price(_price_from_block(pay)[0]) == Decimal("1349.10")
    assert parse_price(_price_from_block(struck)[0]) == Decimal("1499.00")


# ── التثبيت على حاوية ─────────────────────────────────────────────────────


def test_sponsored_prices_outside_the_container_are_ignored():
    """صفحة الكرسي فيها 31 كتلة a-price: أقساط وملحقات وإعلانات.

    مسح عام لـ .a-price يلتقط 215.59 (ملحق) أو '$00' (حزمة مكسورة)
    أو 449.70 (قسط من ثلاثة). التثبيت هو اللي يمنع ذلك.
    """
    noise = (
        '<div id="sp_detail">' + a_price("SAR", "2,392", ".", "00", offscreen="SAR 2,392.00") + "</div>"
        '<div id="ProductSpecs-2">' + a_price("SAR", "215", ".", "59", offscreen="SAR215.59") + "</div>"
    )
    html = page(a_price("SAR", "1,349", ".", "10", offscreen=""), extra=noise)
    data = AmazonTracker(SA_URL).parse(soup_of(html), html)
    assert data["container"] == "corePriceDisplay_desktop_feature_div"
    assert parse_price(data["price"]) == Decimal("1349.10")


def test_container_priority_skips_empty_ones():
    """buybox موجودة دائماً وقد تكون فاضية — ما توقف البحث."""
    html = f"""<html><body><div id="centerCol">
      <span id="productTitle">x</span>
      <div id="buybox"></div>
      <div id="corePrice_feature_div">{a_price("SAR", "50", ".", "00", offscreen="SAR 50.00")}</div>
    </div></body></html>"""
    cid, pay, _ = _find_price_blocks(soup_of(html))
    assert cid == "corePrice_feature_div"
    assert pay is not None


# ── القالب المبتور والكابتشا ──────────────────────────────────────────────


def test_stripped_shell_is_rejected():
    """313KB، رمز 200، بلا كابتشا، بلا centerCol. عابر: يُعاد الطلب."""
    shell = (
        '<html><body><div id="dp-container">'
        '<div id="nav-assist-search"></div></div></body></html>'
    )
    assert AmazonTracker(SA_URL).page_is_valid(shell) is False


def test_nav_assist_alone_does_not_mark_a_page_bad():
    """nav-assist موجود على الكاملة والمبتورة سواء — ليس محدد فرز."""
    html = page(a_price("SAR", "1", ".", "00", offscreen="SAR 1.00"))
    html = html.replace("<body>", '<body><div id="nav-assist-cart"></div>')
    assert AmazonTracker(SA_URL).page_is_valid(html) is True


def test_captcha_is_rejected():
    html = "<html><body>Enter the characters you see below</body></html>"
    assert AmazonTracker(SA_URL).page_is_valid(html) is False


def test_complete_page_is_accepted():
    html = page(a_price("SAR", "1", ".", "00", offscreen="SAR 1.00"))
    assert AmazonTracker(SA_URL).page_is_valid(html) is True


# ── التوفر وحجب الموقع ────────────────────────────────────────────────────


def test_delivery_block_is_not_out_of_stock():
    """بريطانيا حياً: #outOfStock موجود ونصه عن موقع التوصيل لا المخزون.

    المنتج يُباع في بريطانيا؛ أمازون يخفيه عن IP سعودي. تنبيه
    "نفد المخزون" هنا كذب على مستخدم البوت.
    """
    html = """<html><body><div id="centerCol"><span id="productTitle">x</span>
      <div id="outOfStock">This item cannot be dispatched to your selected
      delivery location. Please choose a different delivery location.</div>
      <div id="availability">This item cannot be dispatched to your selected
      delivery location.</div></div></body></html>"""
    out = _availability(soup_of(html))
    assert out["in_stock"] is False
    assert out["location_blocked"] is True


def test_genuine_out_of_stock_is_not_flagged_as_location_blocked():
    html = """<html><body><div id="outOfStock">Currently unavailable.
      We don't know when or if this item will be back in stock.</div></body></html>"""
    out = _availability(soup_of(html))
    assert out["in_stock"] is False
    assert "location_blocked" not in out


def test_availability_text_is_kept_in_the_store_language():
    """نجبر لغة السوق، فالنص يجي بالألمانية على amazon.de.

    مطابقة 'In Stock' كانت راح تفشل صامتة على كل نطاق غير إنجليزي.
    """
    html = '<html><body><div id="availability">Nur noch 15 auf Lager</div></body></html>'
    out = _availability(soup_of(html))
    assert out["availability_text"] == "Nur noch 15 auf Lager"
    assert "in_stock" not in out or out["in_stock"] is not False


def test_blocked_page_yields_no_price_instead_of_an_error():
    html = """<html><body><div id="centerCol"><span id="productTitle">Controller</span>
      <div id="buybox"></div>
      <div id="outOfStock">This item cannot be dispatched to your selected
      delivery location.</div></div></body></html>"""
    data = AmazonTracker(UK_URL).parse(soup_of(html), html)
    assert data.get("price") is None
    assert data["name"] == "Controller"
    assert data["location_blocked"] is True


# ── السوق واللغة ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,tld",
    [
        ("https://www.amazon.sa/dp/B0X", "sa"),
        ("https://www.amazon.co.uk/dp/B0X", "co.uk"),
        ("https://www.amazon.de/-/en/thing/dp/B0X", "de"),
        ("https://smile.amazon.com/dp/B0X", "com"),
        ("https://www.amazon.com.au/dp/B0X", "com.au"),
    ],
)
def test_tld_suffix(url, tld):
    assert _tld_suffix(url) == tld


def test_german_market_pins_language_and_currency():
    """اللغة والعملة محوران منفصلان — لازم الاثنان معاً.

    de-DE وحدها أعطت SAR بتنسيق ألماني. الكوكي وحده غير مختبر منفرداً.
    """
    t = AmazonTracker(DE_URL)
    assert t.accept_language.startswith("de-DE")
    assert t.request_kwargs()["cookies"]["i18n-prefs"] == "EUR"
    assert t.request_kwargs()["cookies"]["lc-acbde"] == "de_DE"


def test_saudi_market():
    t = AmazonTracker(SA_URL)
    assert t.request_kwargs()["cookies"]["i18n-prefs"] == "SAR"


def test_unknown_domain_falls_back_without_locale_cookie():
    t = AmazonTracker("https://www.amazon.co.za/dp/B0X")
    cookies = t.request_kwargs()["cookies"]
    assert "i18n-prefs" in cookies
    assert len(cookies) == 1


def test_locale_override():
    t = AmazonTracker(DE_URL, locale="en-GB:GBP")
    assert t.accept_language.startswith("en-GB")
    assert t.request_kwargs()["cookies"]["i18n-prefs"] == "GBP"


def test_currency_read_from_page_not_only_from_domain():
    html = page(a_price("€", "314", ",", "89", offscreen=""))
    data = AmazonTracker(DE_URL).parse(soup_of(html), html)
    assert data["currency"] == "EUR"


# ── تطبيع الرابط ──────────────────────────────────────────────────────────


def test_canonical_url_drops_tracking_params():
    """متحقق حياً على نطاقين: نفس السعر ونفس الاسم بعد الحذف."""
    messy = (
        "https://www.amazon.de/-/en/2021-Microsoft-Refurbished/dp/B09WVVZQD3/"
        "ref=sr_1_2?_encoding=UTF8&s=computers&sr=1-2&srs=10676131031"
    )
    assert AmazonTracker(messy).normalize_url(messy) == (
        "https://www.amazon.de/dp/B09WVVZQD3"
    )


def test_variant_params_are_kept():
    """th و psc **غير متحقق** أنهما زائدان.

    قد يحملان المتغير المعروض (مقاس/لون) مثل ?sid= عند كارفور.
    نمرّرهما لين يثبت العكس — حذف باراميتر غير مختبر هو الغلطة نفسها.
    """
    url = "https://www.amazon.sa/thing/dp/B0FWXZLD6F/ref=x?th=1&psc=1"
    out = AmazonTracker(url).normalize_url(url)
    assert "th=1" in out and "psc=1" in out and "ref=" not in out


def test_url_without_asin_is_left_alone():
    url = "https://www.amazon.sa/s?k=laptop"
    assert AmazonTracker(url).normalize_url(url) == url


# ── التوجيه ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "domain",
    [
        "www.amazon.sa",
        "www.amazon.de",
        "www.amazon.co.uk",
        "smile.amazon.com",
        "amazon.com.au",
    ],
)
def test_registry_routes_every_amazon_domain(domain):
    """نمط واحد "amazon." يغطي كل النطاقات.

    resolve_tracker تأخذ نطاقاً لا رابطاً — فك الرابط مسؤولية المستدعي.
    """
    from productspy.registry import resolve_tracker

    assert resolve_tracker(domain) is AmazonTracker


def test_registry_rejects_lookalike_domain():
    """المطابقة على حدود التسميات: fakeamazon.com ليس أمازون.

    لو مرّ هذا، فأي نطاق ينتهي بـ 'amazon.com' يوجَّه لنا — وهذا
    بالضبط شكل هجوم تصيّد على بوت يتتبع روابط يرسلها المستخدمون.
    """
    from productspy.exceptions import UnsupportedSiteError
    from productspy.registry import resolve_tracker

    with pytest.raises(UnsupportedSiteError):
        resolve_tracker("www.fakeamazon.com")


# ── تثبيت بلد التوصيل ─────────────────────────────────────────────────────


def test_csrf_token_pattern_matches_the_live_shape():
    """الشكل اللي أصاب حياً على صفحة منتج بريطانية."""
    from productspy.trackers.amazon import _find_csrf

    html = '...{"csrfToken":"1@g68gMJmpFub0QRu1H4IEviXXXX","other":1}...'
    assert _find_csrf(html) == "1@g68gMJmpFub0QRu1H4IEviXXXX"


def test_csrf_falls_back_to_hidden_input():
    from productspy.trackers.amazon import _find_csrf

    html = '<input type="hidden" name="anti-csrftoken-a2z" value="abcdefgh12345">'
    assert _find_csrf(html) == "abcdefgh12345"


def test_no_csrf_token_returns_none_not_an_exception():
    """فشل التثبيت ما يجوز يسقط الجلب — الصفحة الأصلية تبقى صالحة."""
    from productspy.trackers.amazon import _find_csrf

    assert _find_csrf("<html>nothing here</html>") is None


def test_market_carries_a_delivery_country():
    """البلد هو المحور الثالث: يحدد العرض نفسه لا عرضه فقط."""
    assert AmazonTracker(UK_URL).ship_to == "GB"
    assert AmazonTracker(DE_URL).ship_to == "DE"


def test_pin_market_can_be_switched_off():
    tracker = AmazonTracker(UK_URL, pin_market=False)
    assert tracker.ship_to == ""
    assert tracker.recover({}, None) is False


def test_recover_is_a_noop_without_a_country():
    tracker = AmazonTracker("https://www.amazon.co.za/dp/B0X")
    assert tracker.ship_to == ""
    assert tracker.recover({}, None) is False


def test_locale_override_can_set_all_three_axes():
    tracker = AmazonTracker(DE_URL, locale="en-GB:GBP:GB")
    assert tracker.accept_language.startswith("en-GB")
    assert tracker.request_kwargs()["cookies"]["i18n-prefs"] == "GBP"
    assert tracker.ship_to == "GB"


def test_parse_reports_the_market_it_used():
    """السعر بلا سوق عديم المعنى: نفس الـ ASIN له أسعار مشروعة كثيرة."""
    html = page(a_price("£", "24", ".", "99", offscreen=""))
    data = AmazonTracker(UK_URL).parse(soup_of(html), html)
    assert data["market"] == "co.uk"
    assert data["ship_to"] == "GB"