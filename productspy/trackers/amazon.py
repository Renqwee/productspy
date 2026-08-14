"""Amazon tracker — one file covering most Amazon storefronts.

Every selector here came off a live page pulled 2026-08-01/02 from a
Saudi IP. Anything that was not verified says so, in place.

Four findings explain the shape of this file.

1. Amazon answers roughly a third of requests with a stripped 200: a
   313KB document with dp-container but no centerCol, no ppd, no
   productTitle, no price, and no captcha marker anywhere. It is
   transient — the same URL came back full, then stripped, then full
   again on three consecutive tries. page_is_valid catches it and lets
   Fetcher retry. It reports BlockedError rather than ParseError because
   the meaning is "ask again", not "the site changed its layout".

2. a-offscreen, the screen-reader copy that looks like the obvious
   source, came back **empty** inside corePriceDisplay_desktop_feature_div
   on four live pages across three storefronts. Assembling whole and
   fraction is not the fallback here, it is the only path in that
   container. Other containers do fill it, so both are tried.

3. Language, display currency and market are three independent axes:
     Accept-Language  -> page language **and digit grouping**
     i18n-prefs cookie -> the currency **shown**, nothing else
     delivery country -> the offer itself: which seller, which price,
                         whether a price is shown at all
   Evidence separating the first two: de-DE with no currency cookie
   returned 'SAR' alongside '1.363,' — Saudi currency with European
   separators. Evidence separating the third: amazon.de quoting EUR gave
   €314,89, which is 1,363.86 SAR over 4.33 to the cent — the same export
   offer converted, not the domestic German price.

4. No static cookie sets the delivery country. Four direct cookie
   combinations were tried and all failed. The only route is Amazon's own
   address-change endpoint, which returns sst-acb<cc> bound to a
   session-id: a state token, not a value you can copy.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Optional
from urllib.parse import urlsplit, parse_qs
from weakref import WeakKeyDictionary

from bs4 import BeautifulSoup, Tag

from ..base import BaseTracker
from ..models import detect_currency
from ..registry import register
from ..utils.url_tools import currency_from_domain, extract_asin

# ── Text cleanup ───────────────────────────────────────────────────────────
# NFKC is deliberately not used: it expands ﷼ (U+FDFC) into "ريال", and
# _CURRENCY_HINTS in models.py matches on the symbol, so normalising here
# would break currency detection.
#: Direction and zero-width marks, removed outright. Written as escapes on
#: purpose rather than literally: these are invisible in an editor, and any
#: copy/paste or re-encoding can swallow one without a trace.
_ZERO_WIDTH = dict.fromkeys(
    map(
        ord,
        "\u200b\u200e\u200f"            # zero-width space, LRM, RLM
        "\u202a\u202b\u202c"            # embedding and pop-directional
        "\u2066\u2067\u2068\u2069"        # directional isolates
        "\ufeff",                      # BOM appearing mid-text
    ),
    None,
)
#: Odd spaces collapsed to a plain one. \xa0 is the one Amazon puts inside
#: a-offscreen: "SAR\xa01,349.10".
_ODD_SPACES = dict.fromkeys(map(ord, "\xa0\u2007\u2009\u202f"), " ")


def _clean(text: str) -> str:
    """Strip direction marks and normalise spacing.

    This has to run **before** parse_price, not after: we compare strings
    and assemble them here (whole + separator + fraction) before handing
    anything over, so cleaning at the end would be too late.
    models._NOISE does strip \\xa0, but only from the finished text.
    """
    return " ".join(text.translate(_ZERO_WIDTH).translate(_ODD_SPACES).split())


# ── Market map ─────────────────────────────────────────────────────────────
# (Accept-Language, currency, locale cookie name, delivery country code)
#
# Verified live:
#   co.uk -> GB : the product was blocked outright; pinning the country
#                 made the price appear
#   de          : de-DE + i18n-prefs=EUR switched the display to €314,89
#   sa          : unchanged (we are already in that market)
# Everything else is **unverified extrapolation** — lc-acb* names follow a
# known pattern, country codes are ISO-3166. Check the price by eye on the
# first new storefront you try.
_MARKETS: dict[str, tuple[str, str, Optional[str], str]] = {
    "sa": ("en-AE,en;q=0.9,ar;q=0.8", "SAR", "lc-acbsa", "SA"),
    "ae": ("en-AE,en;q=0.9,ar;q=0.8", "AED", "lc-acbae", "AE"),
    "eg": ("en-EG,en;q=0.9,ar;q=0.8", "EGP", "lc-acbeg", "EG"),
    "com": ("en-US,en;q=0.9", "USD", "lc-main", "US"),
    "co.uk": ("en-GB,en;q=0.9", "GBP", "lc-acbuk", "GB"),
    "de": ("de-DE,de;q=0.9,en;q=0.8", "EUR", "lc-acbde", "DE"),
    "fr": ("fr-FR,fr;q=0.9,en;q=0.8", "EUR", "lc-acbfr", "FR"),
    "it": ("it-IT,it;q=0.9,en;q=0.8", "EUR", "lc-acbit", "IT"),
    "es": ("es-ES,es;q=0.9,en;q=0.8", "EUR", "lc-acbes", "ES"),
    "nl": ("nl-NL,nl;q=0.9,en;q=0.8", "EUR", "lc-acbnl", "NL"),
    "ie": ("en-IE,en;q=0.9", "EUR", "lc-acbie", "IE"),
    "se": ("sv-SE,sv;q=0.9,en;q=0.8", "SEK", "lc-acbse", "SE"),
    "pl": ("pl-PL,pl;q=0.9,en;q=0.8", "PLN", "lc-acbpl", "PL"),
    "com.tr": ("tr-TR,tr;q=0.9,en;q=0.8", "TRY", "lc-acbtr", "TR"),
    "co.jp": ("ja-JP,ja;q=0.9,en;q=0.8", "JPY", "lc-acbjp", "JP"),
    "in": ("en-IN,en;q=0.9,hi;q=0.8", "INR", "lc-acbin", "IN"),
    "ca": ("en-CA,en;q=0.9,fr;q=0.8", "CAD", "lc-acbca", "CA"),
    "com.mx": ("es-MX,es;q=0.9,en;q=0.8", "MXN", "lc-acbmx", "MX"),
    "com.br": ("pt-BR,pt;q=0.9,en;q=0.8", "BRL", "lc-acbbr", "BR"),
    "com.au": ("en-AU,en;q=0.9", "AUD", "lc-acbau", "AU"),
    "sg": ("en-SG,en;q=0.9", "SGD", "lc-acbsg", "SG"),
}
_FALLBACK_MARKET = ("en-US,en;q=0.9", "USD", None, "")

# Buy box containers in priority order.
# The first four have been seen live. desktop_buybox and buybox are always
# present but can hold no price at all (the UK page before the country was
# pinned), so they come last.
_PRICE_CONTAINERS = (
    "corePriceDisplay_desktop_feature_div",
    "corePrice_feature_div",
    "corePriceDisplay_mobile_feature_div",
    "apex_offerDisplay_desktop",
    "desktop_buybox",
    "buybox",
)

# Anchoring to a container is load-bearing, not tidiness: a single chair
# page carried 31 a-price blocks — instalments (the price over 3 and over
# 6, the two most frequent numbers on the page), accessories, sponsored
# listings, and one malformed '$00' bundle total. A page-wide sweep picks
# up one of those instead of the price.

_SHELL_MARKERS = ('id="centerCol"', 'id="productTitle"')
_CAPTCHA_MARKERS = (
    "enter the characters you see below",
    "/errors/validatecaptcha",
    "type the characters you see in this image",
)

#: CSRF token for the address-change call. The first pattern is the one
#: that hit live on a UK product page; the others cover A/B layouts.
_CSRF_PATTERNS = (
    r'"csrfToken"\s*:\s*"([^"]{8,})"',
    r'data-csrf-token="([^"]{8,})"',
    r'name="anti-csrftoken-a2z"\s+value="([^"]{8,})"',
)

#: Which (fetcher, host) pairs already had their country pinned
#: **successfully**. Weak keys so we never keep a Fetcher alive. Kept here
#: rather than on the Fetcher: the transport layer knows nothing about
#: Amazon, and store-specific state has no business living there.
_PINNED: "WeakKeyDictionary[Any, set[str]]" = WeakKeyDictionary()

#: Failed attempts per (fetcher, host), so a bad run is retried a few times
#: instead of disabling the pin for the life of the Fetcher.
#:
#: This used to be one set, marked **before** the attempt, on the reasoning
#: that a failure is no reason to loop. The cost of that shortcut was
#: measured on amazon.co.uk: the POST failed once, and every later product
#: on that storefront read an export price with nothing to show for it —
#: the exact silent drift this project is built against. Failing to pin is
#: not the same as being pinned, and only success may say so.
_PIN_FAILURES: "WeakKeyDictionary[Any, dict[str, int]]" = WeakKeyDictionary()

#: Attempts per host before giving up. Bounded because the endpoint is
#: undocumented and may simply stop working — retrying forever would add a
#: POST to every fetch for nothing.
_MAX_PIN_ATTEMPTS = 3

#: Guards both maps. Fetcher is thread-safe behind its own lock while this
#: state was not, which was a documented inconsistency; splitting one set
#: into two structures that must agree is what makes it worth closing.
_PIN_LOCK = threading.Lock()


@register("amazon.")
class AmazonTracker(BaseTracker):
    """The trailing dot in "amazon." means: this label, under any TLD.

    One pattern catches amazon.sa, amazon.de, amazon.co.uk and
    smile.amazon.com. Matching happens on label boundaries, so
    fakeamazon.com does not get through.
    """

    site_name = "Amazon"
    # None on purpose: the currency is derived from the domain through
    # currency_from_domain. That works here **because** we pin the market
    # to the domain's own country, so the domain-derived value and the one
    # read off the page agree. Without pinning, amazon.de shows SAR while
    # the domain says EUR.
    default_currency: Optional[str] = None

    def __init__(self, url: str, fetcher=None, locale: Optional[str] = None,
                 pin_market: bool = True):
        super().__init__(url, fetcher=fetcher)
        self.tld = _tld_suffix(self.url)
        lang, currency, lc_cookie, country = _MARKETS.get(self.tld, _FALLBACK_MARKET)
        if locale:
            # Explicit override: "en-GB", "en-GB:GBP" or "en-GB:GBP:GB"
            parts = locale.split(":")
            lang = f"{parts[0]},{parts[0].split('-')[0]};q=0.9"
            if len(parts) > 1 and parts[1]:
                currency = parts[1]
            if len(parts) > 2 and parts[2]:
                country = parts[2]
        self.accept_language = lang
        self.market_currency = currency
        self.ship_to = country if pin_market else ""
        self._cookies: dict[str, str] = {"i18n-prefs": currency}
        if lc_cookie:
            # 'de-DE,de;q=0.9,en;q=0.8' -> 'de_DE'
            self._cookies[lc_cookie] = lang.split(",")[0].replace("-", "_")

    # ── Hooks added by the base.py patch ───────────────────────────────

    def request_kwargs(self) -> dict[str, Any]:
        return {"cookies": self._cookies}

    def page_is_valid(self, html: str) -> bool:
        """Tell a complete page apart from the stripped shell and a captcha.

        A string check rather than BeautifulSoup, for two reasons: it runs
        inside the retry loop against a ~1.9MB body, so parsing the whole
        document on every failed attempt is waste; and more importantly it
        is handed to http.py, so parsing HTML in here would drag page
        knowledge into the transport layer.

        Experience inverted the rule: success means the product container
        is present, not that a captcha is absent. The stripped shell
        carries no captcha marker at all, and any check built on captcha
        markers walks straight past it.
        """
        low = html.lower()
        if any(marker in low for marker in _CAPTCHA_MARKERS):
            return False
        return all(marker in html for marker in _SHELL_MARKERS)

    def recover(self, data: dict[str, Any], response) -> bool:
        """Pin the delivery country once and ask for a single re-fetch.

        Why reactive after the first fetch rather than proactive before it:
        the CSRF token is read off the product page itself, so that fetch
        has to happen either way. Running it up front would mean two
        requests every time instead of one in the common case.

        Why once per (fetcher, host): Amazon keeps the state in the session
        as sst-acb<cc>, and a Fetcher holds one long-lived session, so the
        pin carries over to every later product on that storefront.

        A warning about proxies: _next_proxy() rotates per request. With
        proxies enabled the POST may leave from one IP and the following
        fetch from another, and Amazon most likely ties session state to
        the IP — unverified. If that happens, pin a single proxy or pass
        pin_market=False.

        **Only success marks the host.** A failure counts against a small
        budget and is retried on the next product, because the alternative
        — seen live on amazon.co.uk — is one failed POST silently
        committing the Fetcher to export prices forever. When the budget
        runs out the caller is told through data["market_pin_failed"]
        rather than left to wonder why the currency looks wrong.
        """
        if not self.ship_to or self.fetcher is None:
            return False
        host = urlsplit(self.url).netloc
        try:
            with _PIN_LOCK:
                pinned = _PINNED.setdefault(self.fetcher, set())
                failures = _PIN_FAILURES.setdefault(self.fetcher, {})
                if host in pinned:
                    return False
                attempts = failures.get(host, 0)
                if attempts >= _MAX_PIN_ATTEMPTS:
                    data["market_pin_failed"] = True
                    return False
        except TypeError:
            # Fetcher does not accept weak references (a bare test double,
            # say). That is no reason to fail the fetch — skip the pin.
            return False

        # Outside the lock: this is a network call, and holding a lock
        # across it would serialise every thread behind the slowest POST.
        ok = self._pin_delivery_country(response.text)

        with _PIN_LOCK:
            if ok:
                pinned.add(host)
                failures.pop(host, None)
            else:
                failures[host] = attempts + 1
        if not ok:
            data["market_pin_failed"] = True
        return ok

    # ── URL normalisation ──────────────────────────────────────────────

    def normalize_url(self, url: str) -> str:
        """Rebuild from the ASIN, dropping ref=, _encoding and sr= at once.

        Verified on two storefronts: amazon.sa and amazon.de returned the
        same price and the same name for the original URL and for the bare
        /dp/{ASIN}.

        **Not verified**: do th=1&psc=1 switch the variant on display
        (size, colour)? So they stay. Dropping a parameter we never tested
        is exactly the mistake that cost us on Carrefour with ?sid=.
        """
        asin = extract_asin(url)
        tld = _tld_suffix(url)
        if not asin or not tld:
            return url
        base = f"https://www.amazon.{tld}/dp/{asin}"
        query = parse_qs(urlsplit(url).query)
        keep = [f"{k}={query[k][0]}" for k in ("th", "psc") if query.get(k)]
        return f"{base}?{'&'.join(keep)}" if keep else base

    # ── Extraction ─────────────────────────────────────────────────────

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        # No JSON-LD on Amazon: zero ld+json blocks across four pages from
        # three storefronts. The DOM path is the only path.
        data: dict[str, Any] = {}

        title = soup.find(id="productTitle")
        data["name"] = _clean(title.get_text(strip=True)) if title else None

        container, pay_block, struck_block = _find_price_blocks(soup)
        data["container"] = container

        if pay_block is not None:
            price_text, source = _price_from_block(pay_block)
            data["price"] = price_text
            data["price_source"] = source
            if price_text:
                data["currency"] = detect_currency(
                    price_text, currency_from_domain(f"amazon.{self.tld}")
                )

        if struck_block is not None:
            list_text, _ = _price_from_block(struck_block)
            # list_price == price is not a deal, so it is dropped, not stored
            if list_text and list_text != data.get("price"):
                data["list_price"] = list_text

        data.update(_availability(soup))

        seller = soup.find(id="sellerProfileTriggerId") or soup.find(id="merchant-info")
        data["seller"] = _clean(seller.get_text(" ", strip=True)) if seller else None

        image = soup.find(id="landingImage")
        if isinstance(image, Tag):
            data["image"] = image.get("data-old-hires") or image.get("src")

        data["sku"] = extract_asin(self.url)
        data["market"] = self.tld
        data["ship_to"] = self.ship_to
        # Whether the price above is a local one or an export quote is the
        # difference between two legitimate numbers measuring different
        # things (see the VAT evidence in the module docstring), so it
        # belongs in raw rather than being inferred from the currency.
        data["market_pinned"] = self._host_is_pinned()
        return data

    def _host_is_pinned(self) -> Optional[bool]:
        """True/False once pinning applies, None when it does not.

        None means the question is moot — pin_market=False, or a Fetcher
        that cannot be weak-referenced — and is not the same as False,
        which means we tried and the offer may still be an export one.
        """
        if not self.ship_to or self.fetcher is None:
            return None
        try:
            with _PIN_LOCK:
                return urlsplit(self.url).netloc in _PINNED.get(self.fetcher, set())
        except TypeError:
            return None

    # ── Address-change call ────────────────────────────────────────────

    def _pin_delivery_country(self, html: str) -> bool:
        """Tell Amazon we ship to the storefront's country.

        Returns True when the caller should fetch again.

        Verified live on amazon.co.uk: a product that answered 'This item
        cannot be dispatched to your selected delivery location' showed its
        price right after this call. The server replied
        {"isValidAddress":1,"isAddressUpdated":1,...,"countryCode":"GB",
         "zipCode":"DN3 3JP",...} — Amazon picks a default postcode for the
        country itself, so we never pass one.

        The endpoint is internal and undocumented: its name and payload can
        change without notice. So every failure here is swallowed and
        returns False. The original page stays usable, and the worst case
        is reading an export-market price instead of a local one rather
        than failing outright.
        """
        token = _find_csrf(html)
        if not token:
            return False
        post = getattr(self.fetcher, "post", None)
        if post is None:
            return False

        endpoint = (
            f"https://www.amazon.{self.tld}"
            "/portal-migration/hz/glow/address-change?actionSource=glow"
        )
        try:
            response = post(
                endpoint,
                data={
                    "locationType": "COUNTRY",
                    "district": self.ship_to,
                    "countryCode": self.ship_to,
                    "deviceType": "web",
                    "storeContext": "NoStoreName",
                    "pageType": "Detail",
                    "actionSource": "glow",
                },
                accept_language=self.accept_language,
                # Only what is specific to this call. The XHR shape —
                # X-Requested-With, the Sec-Fetch-* trio, Accept: */* —
                # now comes from Fetcher.xhr_headers, so it is no longer
                # restated here and cannot drift out of step with it.
                headers={
                    "anti-csrftoken-a2z": token,
                    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "origin": f"https://www.amazon.{self.tld}",
                    "referer": self.url,
                },
                cookies=self._cookies,
            )
            payload = json.loads(response.text)
        except Exception:
            return False
        return bool(payload.get("isAddressUpdated"))


# ── Module-level helpers, kept out of the class so each tests alone ───────


def _tld_suffix(url: str) -> str:
    """'https://www.amazon.co.uk/dp/X' -> 'co.uk'"""
    host = urlsplit(url).netloc.lower().split(":")[0]
    host = re.sub(r"^(www|smile)\.", "", host)
    match = re.match(r"amazon\.(.+)$", host)
    return match.group(1) if match else ""


def _find_csrf(html: str) -> Optional[str]:
    for pattern in _CSRF_PATTERNS:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


#: Wrappers holding the Subscribe & Save quote rather than the purchase
#: price. Measured on amazon.sa B0BJKY2QC9, which offers both: the page
#: says "One-time purchase SAR197.95" and "Subscribe & Save SAR178.15",
#: a 10% auto-delivery discount on a different commitment entirely.
_SUBSCRIPTION_CONTAINERS = frozenset({
    "snsAccordionRowMiddle",
    "subscriptionPrice",
    "sns-base-slot",
})


def _in_subscription_block(block: Tag) -> bool:
    """Is this a-price inside a subscription offer rather than the buy box?"""
    node = block.parent
    while node is not None and getattr(node, "get", None) is not None:
        if node.get("id") in _SUBSCRIPTION_CONTAINERS:
            return True
        node = node.parent
    return False


def _find_price_blocks(soup: BeautifulSoup):
    """First container holding a real price, plus its pay and struck blocks.

    data-a-strike="true" is what tells them apart, not the class name: one
    live page carried both apex-basisprice-value and apex-basis-price-value,
    two spellings of the same thing (the first in the main container, the
    second in sponsored listings). Keying on the class breaks at the first
    A/B test.

    **Subscription prices are excluded outright**, not merely outranked.
    On a page offering both, the first three containers hold only the
    one-time price and taking pay[0] happens to be right — but
    desktop_buybox and buybox, the last two entries, carry seven a-price
    blocks with the subscription quote sitting among them. There pay[0]
    is correct only because the DOM lists "One-time purchase" before
    "Subscribe & Save", which is Amazon's layout choice on that day and
    not a fact about the offer. Excluding the subscription wrappers turns
    the safety from an ordering coincidence into a rule, and it changes
    nothing on pages that have no subscription at all.
    """
    for container_id in _PRICE_CONTAINERS:
        node = soup.find(id=container_id)
        if not isinstance(node, Tag):
            continue
        blocks = node.select("span.a-price")
        pay = [
            b for b in blocks
            if b.get("data-a-strike") != "true" and not _in_subscription_block(b)
        ]
        if not pay:
            continue
        struck = [b for b in blocks if b.get("data-a-strike") == "true"]
        return container_id, pay[0], (struck[0] if struck else None)
    return None, None, None


def _price_from_block(block: Tag) -> tuple[Optional[str], Optional[str]]:
    """Price out of one a-price block, plus the name of the path taken.

    Two paths, because neither covers the ground alone:

    - a-offscreen: the fully formatted screen-reader copy. Came back
      **empty** inside corePriceDisplay_desktop_feature_div on four live
      pages, and populated inside corePrice_feature_div on the same page at
      the same moment. So it is tried, then checked for emptiness before
      being trusted.

    - whole + fraction: a naive get_text() on an a-price block yields
      'SAR1,349.10SAR1,349.10', because it holds an a-offscreen copy and an
      aria-hidden duplicate — the number is doubled literally, not loosely.

    The decimal separator is read from a-price-decimal because it follows
    Accept-Language, not the currency: amazon.de returned 'SAR' with
    '1.363,' and ','. Hardcoding '.' reads 1.363,86 as 1363 or as 1.363
    depending on the day — off by a factor of a thousand, and silent.

    And a-price-decimal sits **inside** a-price-whole, so the whole text
    arrives as '1,349.' with the separator trailing. We strip it, since we
    assemble the number ourselves.
    """
    offscreen = block.select_one(".a-offscreen")
    if offscreen is not None:
        text = _clean(offscreen.get_text(strip=True))
        if text:
            return text, "offscreen"

    whole = block.select_one(".a-price-whole")
    if whole is None:
        return None, None

    decimal_el = block.select_one(".a-price-decimal")
    separator = _clean(decimal_el.get_text(strip=True)) if decimal_el else "."

    number = _clean(whole.get_text(strip=True)).rstrip(".,٫، ")
    fraction_el = block.select_one(".a-price-fraction")
    fraction = _clean(fraction_el.get_text(strip=True)) if fraction_el else ""
    if fraction:
        number = f"{number}{separator}{fraction}"

    symbol_el = block.select_one(".a-price-symbol")
    symbol = _clean(symbol_el.get_text(strip=True)) if symbol_el else ""
    return (f"{symbol} {number}".strip() if symbol else number), "whole+frac"


#: Delivery-location block wording. Amazon puts this inside #outOfStock, so
#: the id alone does not mean the item is out of stock: the UK product
#: returned #outOfStock while it was in stock and selling — the block is on
#: where the request came from, not on inventory. Confirmed by the price
#: appearing the moment the delivery country was pinned, nothing else
#: changed.
#: The German arm was written as 'nicht an (deine|die) ausgew' and never
#: matched anything: the live sentence is 'kann nicht an **den von dir**
#: ausgewählten Lieferort versendet werden' (B09WVVZQD3). Four words sat
#: between the two anchors and the alternation allowed one. Location blocks
#: on amazon.de went undetected from the day it was written — invisible
#: because a missed block reads as an ordinary page, not as an error.
#: Hence the gap is spanned by a bounded wildcard now, and the second
#: German arm matches the follow-up sentence independently.
_DISPATCH_BLOCK = re.compile(
    r"cannot be (dispatched|shipped) to|"
    r"choose a different delivery location|"
    r"nicht an .{0,30}?ausgew|"
    r"w[äa]hle einen anderen lieferort|"
    r"ne peut pas [êe]tre livr",
    re.I,
)

#: Where the block wording has been seen. #outOfStock is the documented
#: home, but amazon.de put it in the delivery line instead, on a page with
#: **no #outOfStock at all** and a stock count of 16 sitting right above it
#: (B09WVVZQD3, live). Reading only #outOfStock there produced no in_stock
#: key whatsoever — not even a None — on a plain location block.
_BLOCK_CONTAINERS = (
    "outOfStock",
    "deliveryBlockMessage",
    "addToCart_feature_div",
)

#: A store saying "out of stock" **while still offering a cart button**.
#: Amazon backorders: 'Temporarily out of stock. Order now and we'll deliver
#: when available.' — verified live on amazon.sa B0DWZDWRVW, which the cart
#: button alone reported as in stock.
#:
#: Wording, not colour, because colour does not survive the border:
#: a-color-success does mean in stock, but its **absence** means nothing.
#: amazon.de returned a-color-price on 'Nur noch 16 auf Lager' (16 left, in
#: stock) and amazon.sa returned a-color-base on 'Temporarily out of stock'
#: — same "not success", opposite meanings.
#:
#: Only the English arm is verified live. The rest is extrapolation from
#: Amazon's own standard strings, and is written to fail closed: every
#: alternative needs a negation or an explicit stock-out phrase, so the
#: in-stock wordings we have actually seen — 'In Stock', 'Auf Lager',
#: 'Nur noch 16 auf Lager', 'Usually ships within 7 to 8 days' — cannot
#: match any of them.
_OUT_OF_STOCK_TEXT = re.compile(
    r"out of stock|currently unavailable|"        # en (verified)
    r"nicht auf lager|nicht verf[üu]gbar|"        # de
    r"rupture de stock|actuellement indisponible|"  # fr
    r"sin stock|no disponible|"                   # es
    r"non disponibile|"                           # it
    r"niet op voorraad|"                          # nl
    r"غير متوفر|نفد",                              # ar
    re.I,
)


def _availability(soup: BeautifulSoup) -> dict[str, Any]:
    """Availability from signals that are as language-independent as possible.

    We pin the market's language, so #availability comes back in German on
    amazon.de ('Nur noch 15 auf Lager'). Matching 'In Stock' would have
    failed silently on every non-English storefront — hence the primary
    test being element presence rather than wording, with the raw text kept
    for the caller.

    Seven states, all measured live 2026-08-14:

        page                       #outOfStock  cart  in_stock
        sa B0FWXZLD6F 'In Stock'       -         yes   True
        sa B0CDL3CQHV 'ships 7-8d'     -         yes   True
        sa B0863TXGM3 unavailable     yes         -    False
        sa B0DWZDWRVW 'Temporarily     -        yes    False + backorderable
                       out of stock'
        com B0000AZK4G location       yes         -    None + location_blocked
        de  B09WVVZQD3 location        -          -    None + location_blocked
                       ('Nur noch 16 auf Lager' — block is in the
                        delivery line, no #outOfStock anywhere)
        com B0002E1G5C no offer        -          -    None + no_featured_offer
                       (same URL pinned to US: cart, 'In Stock', $12.99)

    Note rows 4 and 6: neither #outOfStock nor the cart button decides on
    its own. A cart button appears on a stocked-out backorder, and a
    location block appears with no #outOfStock at all.

    **The cart button is not proof of stock.** B0DWZDWRVW offers it while
    saying 'Temporarily out of stock. Order now and we'll deliver when
    available.' — Amazon takes the order and ships it whenever the item
    returns. Reading the button reported it as in stock, which is the alert
    inverted. So the wording is checked first, and `backorderable` keeps
    the distinction from a dead listing.

    Rows 5-7 return None on purpose, and all three used to return something
    else. None of those pages says anything about inventory, so any boolean
    is invented:

    - **Location block is not stock.** Amazon serves the refusal inside
      #outOfStock, and reading the id alone reported False for an item that
      was selling — just not to us. That is a false "out of stock" alert on
      a live listing, and it is silent, since the number never moves again.
      It is checked across _BLOCK_CONTAINERS rather than one id because
      amazon.de puts the same sentence in the delivery line instead.
      If this key survives a country pin, the pin did not take — see recover.

    - **No featured offer is not stock either**, and on the one page we
      have it was the location block in disguise. B0002E1G5C carries no buy
      box at all from an unpinned Saudi IP: #unqualifiedBuyBox_feature_div,
      a 'See All Buying Options' link, an **empty** #availability, no cart
      button — and, unlike the state above, **no sentence saying why**.
      The same URL through the full pipeline, country pinned to US, returns
      'In Stock' at $12.99. So Amazon has two ways of hiding an offer from
      a location and only one of them explains itself; False here would be
      a false out-of-stock alert on an item selling at full price.
      Its two 'Currently unavailable' strings are twister variation
      **templates** in a JS blob, not page state — reading those is the
      Jarir stock_status trap, so the marker is the container, not wording.
      Unverified: whether this state ever survives a successful pin. If it
      does, the cause there is something other than location.

    in_stock_source names whichever signal decided, on the Jarir pattern:
    a None in the field alone cannot say whether nothing matched or
    something matched and refused to guess.
    """
    out: dict[str, Any] = {}
    availability = soup.find(id="availability")
    # Present-but-empty is a real live state (B0002E1G5C), and an empty
    # string in raw reads like a store that answered blank rather than one
    # that was never asked.
    text = _clean(availability.get_text(" ", strip=True)) if availability is not None else ""
    if text:
        out["availability_text"] = text

    # The narrowest carrier of the stock sentence, and the one to match on:
    # #availability can pick up neighbouring furniture, this span holds the
    # message alone ('Temporarily out of stock.').
    message_el = soup.select_one(".primary-availability-message")
    message = _clean(message_el.get_text(" ", strip=True)) if message_el is not None else text

    out_of_stock = soup.find(id="outOfStock")
    # Not verified: is #add-to-cart-button always present on an in-stock
    # page? Not yet checked against a live one.
    cart = soup.find(id="add-to-cart-button") or soup.find(id="buy-now-button")
    no_offer = soup.find(id="unqualifiedBuyBox_feature_div")

    blocks = [text]
    for container_id in _BLOCK_CONTAINERS:
        node = soup.find(id=container_id)
        if node is not None:
            blocks.append(_clean(node.get_text(" ", strip=True)))
    blocked = any(_DISPATCH_BLOCK.search(b) for b in blocks)

    if out_of_stock is not None:
        # #availability holds the same sentence without the wishlist and
        # "similar items" furniture the surrounding box drags in, so it is
        # preferred when it has anything to say.
        out["unavailable_reason"] = (text or blocks[1])[:200]

    # Order matters, and the location block comes first on purpose: it
    # outranks every other signal because it says nothing about stock at
    # all. amazon.de proved the two are independent — 'Nur noch 16 auf
    # Lager' (16 left) sitting directly above a refusal to ship here.
    if blocked:
        out["in_stock"] = None
        out["location_blocked"] = True
        out["in_stock_source"] = "location_blocked"
    elif out_of_stock is not None:
        out["in_stock"] = False
        out["in_stock_source"] = "outOfStock"
    elif message and _OUT_OF_STOCK_TEXT.search(message):
        # Checked **before** the cart button, which is the whole point: on a
        # backorder Amazon says "Temporarily out of stock" and offers the
        # button anyway. Trusting the button there reported an out-of-stock
        # item as in stock — the exact inversion of the alert the caller
        # wants.
        out["in_stock"] = False
        out["unavailable_reason"] = message[:200]
        out["in_stock_source"] = "availability_text"
        if cart is not None:
            # Orderable, just not held: the caller may want to treat this
            # differently from a dead listing, and only this key says which.
            out["backorderable"] = True
    elif cart is not None:
        out["in_stock"] = True
        out["in_stock_source"] = "cart"
    elif no_offer is not None:
        out["in_stock"] = None
        out["no_featured_offer"] = True
        out["in_stock_source"] = "no_featured_offer"
    return out