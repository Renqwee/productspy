from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url


@register("carrefourksa.com")
class CarrefourTracker(BaseTracker):
    """Carrefour KSA (Majid Al Futtaim storefront).

    The one thing to know before touching this file: **Carrefour's
    JSON-LD price is wrong.** Verified live on SKU 733391 (AirPods Pro 2,
    selling at 709.00 SAR, was 1049.00):

        "offers": {"@type":"Offer","priceCurrency":"SAR","price":"340",
                   "availability":"https://schema.org/InStock"}

    340 is the *discount amount*, not the price. Taking the shared
    from_json_ld() path unchanged would have the bot tracking 709 SAR
    headphones as a 340 SAR item — and since that number is stable, the
    bot fires one bogus price-drop alert and then goes quiet forever on a
    wrong figure. A silent wrong number is worse than a loud failure, so
    the JSON-LD price is discarded here on purpose, not merely
    overridden. Everything *else* in that block (name, sku, image,
    availability, priceCurrency) checked out against the page and is
    still used.

    The real numbers live in the React Server Components flight payload
    that Next.js App Router streams inside <script> tags. There is no
    __NEXT_DATA__ on this platform — that belonged to the older pages
    router, and looking for it is a dead end.

    carrefourksa.com is a .com that quotes SAR only, so default_currency
    is set explicitly instead of being derived from the TLD (which would
    say USD).

    Sibling storefronts (carrefouruae.com, carrefourqatar.com, ...) run
    the same platform but each quotes a different currency, so they are
    NOT registered here — adding one means a subclass with its own
    default_currency, not another pattern on this class.
    """

    site_name = "Carrefour"
    default_currency = "SAR"
    accept_language = "en-SA,en;q=0.9,ar;q=0.8"

    # ---- URL handling -------------------------------------------------
    #
    # Bisected live over all 8 subsets of ?offer=&sid=&sellerId= on one
    # product. Only `sid` moves anything:
    #
    #   (none)              -> no price, OutOfStock, 515,442 bytes
    #   offer               -> no price, OutOfStock, 515,505
    #   sellerId            -> no price, OutOfStock, 515,444
    #   sid                 -> price 340*, InStock,  581,440
    #   sid,sellerId        -> price 340*, InStock,  583,703
    #                          (* the bogus JSON-LD figure; the flight
    #                           payload carried 709.00 in every case)
    #
    # sid is the service/fulfilment id. Without it the storefront cannot
    # resolve which store serves the address, so it renders the PDP as
    # out of stock and strips every price component — 66KB of markup
    # simply is not emitted. So sid is not tracking noise: it is the
    # param the page is unusable without.
    _KEEP_PARAMS = ("sid",)

    # Injected when the incoming URL has none. This is a real assumption:
    # a link copied from search or shared from the app often arrives
    # clean, and fetching it as-is yields a permanent "out of stock, no
    # price" for a product that is actually in stock. EXPRESS is the
    # value observed live; other modes (scheduled delivery, in-store)
    # exist and were NOT compared, so if Carrefour ever prices the same
    # item differently per fulfilment mode, this line decides which price
    # the bot tracks. Chosen deliberately over silently reporting None.
    _DEFAULT_SID = "EXPRESS"

    # PDP path shape, verified on two live URLs:
    #   /mafsau/en/smartphones/apple-iphone-11-.../p/SA190199220423
    #   /mafsau/en/true-wireless-earbuds/apple-airpods-.../p/733391
    # The segment after /p/ is the store SKU — short numeric or long
    # supplier-style, both occur. It also appears inside the CDN image
    # path (.../63607269261342/733391_main.jpg), which is what confirms
    # it is the real product code and not a slug hash.
    _SKU_RE = re.compile(r"/p/([A-Za-z0-9_-]+)")

    # Live <title> / og:title shape: "Buy <name> Online | Carrefour KSA".
    # Only used when there is no <h1>; the wrapper has to come off or the
    # bot stores "Buy Apple iPhone 11 ... Online | Carrefour KSA" as the
    # product name and every alert reads like an ad.
    _TITLE_RE = re.compile(r"^\s*buy\s+(?P<name>.+?)\s+online\s*$", re.IGNORECASE)

    # ---- flight-payload patterns --------------------------------------
    #
    # Every one of these anchors on a *quoted* key. That is what keeps
    # them off the analytics twins sitting in the same object:
    #     "oneGMSellingPrice":0.709   "oneGMMarkedPrice":1.049
    # which are the same numbers divided by a thousand. `"price"` cannot
    # match `SellingPrice"` because the quote must come immediately
    # before a lowercase p; same trick guards unitPrice against
    # effectiveUnitPrice.
    # The ld+json block has to come out of the document before any of the
    # patterns below run. It is plain (unescaped) JSON containing
    # "price":"340" right next to "sku":"733391" — so the SKU anchor,
    # which is supposed to prove a number belongs to this product, would
    # instead vouch for the one number on the page we know is wrong. The
    # discard in parse() only clears the mapped dict; without this the
    # bad figure walks back in through the text scan.
    _LD_JSON_RE = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>.*?</script>',
        re.IGNORECASE | re.DOTALL,
    )

    _FINAL_PRICE_RE = re.compile(r'"finalPrice"\s*:\s*"([\d.,]+)"')
    _PRICE_RE = re.compile(r'"price"\s*:\s*"([\d.,]+)"')
    _DISCOUNT_RE = re.compile(r'"discount"\s*:\s*"([\d.,]+)"')
    # Unquoted value, so unlike the three above it has no closing quote
    # to stop at: `"unitPrice":1049,"effectiveUnit":1` would hand back
    # "1049," and Decimal chokes on the comma. The alternation ends the
    # match on a digit.
    _UNIT_PRICE_RE = re.compile(r'"unitPrice"\s*:\s*(\d[\d.,]*\d|\d)')

    # How far from a match we will look for the SKU before believing the
    # number belongs to this product rather than to a recommendation
    # carousel item further down the payload.
    _ANCHOR_WINDOW = 2000

    def normalize_url(self, url: str) -> str:
        """Keep `sid`, drop everything else, add `sid` if it is missing.

        Two different jobs in one method, both load-bearing:

        1. Dropping utm_*, offer=, sellerId= keeps the same product from
           being stored as several tracked items with separate price
           histories — the reason canonical_url exists.
        2. Keeping (or adding) sid keeps the page renderable at all.

        Not verified: whether a param exists that selects a marketplace
        seller the way ?o= does on Noon. sellerId=0000 looked like one,
        but changed nothing in the bisect — 0000 is Carrefour itself, and
        no third-party-sold product was tested.
        """
        cleaned = canonical_url(url, keep_params=self._KEEP_PARAMS)
        if not urlparse(cleaned).query:
            cleaned = f"{cleaned}?sid={self._DEFAULT_SID}"
        return cleaned

    # ---- parsing ------------------------------------------------------

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        data: dict[str, Any] = {}

        product = self.find_json_ld_product(soup)
        if product:
            data = self.from_json_ld(product)
            # See the class docstring: this field is the discount amount.
            # Dropped before anything downstream can read it.
            data["price"] = None

        sku = data.get("sku") or self._sku_from_url(self.url)
        data.update(self._from_flight(html, sku))

        # No early return: the sources above fill different fields, and
        # the page-level ones only patch holes — an existing value is
        # never overwritten.
        for key, value in self._from_page(soup).items():
            if data.get(key) in (None, ""):
                data[key] = value

        # Carrefour double-encodes: the JSON-LD string itself contains
        # the literal characters "&ndash;", so json.loads hands back
        # 'Kenwood Air Fryer HFP52.000BK &ndash; 5 L' (live, SKU 756010).
        # Left alone it goes into the bot's database and out into every
        # alert exactly like that. Applied here rather than in
        # BaseTracker because this is the only store it has been seen on
        # — if noon or extra ever show it, that is the moment to move it
        # up, not before.
        if data.get("name"):
            data["name"] = html_unescape(str(data["name"])).strip()

        # A list price equal to (or below) the selling price is not an
        # offer. Live on SKU 765044, an undiscounted speaker: price
        # 79.00 and unitPrice 79. Keeping it would have to_dict() report
        # "was 79, now 79" — discount_pct already returns None there, but
        # the raw field would still be lying about an offer existing.
        self._drop_non_offer_list_price(data)

        return data

    @staticmethod
    def _drop_non_offer_list_price(data: dict[str, Any]) -> None:
        from decimal import Decimal, InvalidOperation

        raw_list, raw_price = data.get("list_price"), data.get("price")
        if raw_list is None or raw_price is None:
            return
        try:
            if Decimal(str(raw_list)) <= Decimal(str(raw_price)):
                data["list_price"] = None
        except (InvalidOperation, ValueError):
            data["list_price"] = None

    # ---- RSC flight payload -------------------------------------------

    def _from_flight(self, html: str, sku: Optional[str]) -> dict[str, Any]:
        """Price and pre-discount price out of the streamed RSC payload.

        The payload is embedded as JavaScript string literals, so every
        inner quote arrives backslash-escaped:

            ...,\\"discount\\":\\"340\\",\\"price\\":\\"709.00\\",...

        Un-escaping once up front is what lets a single set of patterns
        read both the escaped payload and any plain-JSON island on the
        page. It is a text-level replace rather than json.loads because
        the payload is a stream of numbered chunks (a1:, a3:, c4:) that
        reference each other with "$c3" pointers — it is not one document
        that parses.

        Verified live on SKU 733391: price 709.00, unitPrice 1049,
        discount 340, and 709 + 340 == 1049. NOT verified: a product
        with no discount at all (does `discount` disappear, or come back
        as "0"?), and an out-of-stock product (the whole price block is
        absent there, which is why price may legitimately be None).
        """
        flat = self._LD_JSON_RE.sub(" ", html).replace('\\"', '"')

        price = self._anchored(flat, self._FINAL_PRICE_RE, sku)
        if price is None:
            price = self._anchored(flat, self._PRICE_RE, sku)
        if price is None:
            return {}

        # Pre-discount price, best source first: the storefront's own
        # unitPrice field, then price + discount as a cross-check. On the
        # verified page both routes gave 1049 exactly.
        list_price = self._anchored(flat, self._UNIT_PRICE_RE, sku)
        discount = self._anchored(flat, self._DISCOUNT_RE, sku)

        out: dict[str, Any] = {"price": price}
        if list_price is not None:
            out["list_price"] = list_price
        elif discount is not None:
            out["list_price"] = self._sum(price, discount)
        return out

    def _anchored(self, flat: str, pattern: re.Pattern, sku: Optional[str]):
        """First match whose neighbourhood mentions this product's SKU.

        A Carrefour PDP ships recommendation carousels, and every card in
        them carries its own "price" key in the same payload. Without an
        anchor the first match could be any of them. The SKU appears
        inside the main product's own object (in its image URL), so
        requiring it within a window ties the number to this page.

        With no SKU to anchor on, the first match is returned rather than
        nothing — a name-only result helps nobody, and the main product's
        block precedes the carousels in the stream.
        """
        matches = list(pattern.finditer(flat))
        if not matches:
            return None
        if not sku:
            return matches[0].group(1)
        for match in matches:
            start = max(0, match.start() - self._ANCHOR_WINDOW)
            end = match.end() + self._ANCHOR_WINDOW
            if sku in flat[start:end]:
                return match.group(1)
        return None

    @staticmethod
    def _sum(price: str, discount: str) -> Optional[str]:
        from decimal import Decimal, InvalidOperation

        try:
            total = Decimal(price.replace(",", "")) + Decimal(discount.replace(",", ""))
        except (InvalidOperation, AttributeError):
            return None
        return str(total)

    # ---- page-level fallbacks -----------------------------------------

    def _from_page(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Name, image and SKU from server-rendered markup.

        Verified live: the <h1>, the availability wording and the og:
        meta block all arrive in the server's HTML.

        Deliberately absent: price. It *is* in the DOM, split across
        three elements — <div>SAR</div><div>709</div><div>.<!-- -->00</div>
        — but the only handles on those elements are raw Tailwind classes
        (`text-xl leading-7 font-bold md:text-2xl`), which change on any
        restyle. The flight payload those elements are rendered from is
        the stabler source, so the DOM is left alone.
        """
        name = None
        heading = soup.find("h1")
        if heading:
            name = heading.get_text(strip=True)
        if not name:
            name = self._name_from_title(soup)

        image = None
        og_image = soup.find("meta", property="og:image")
        if og_image:
            image = og_image.get("content") or None

        return {
            "name": name,
            "image": image,
            "sku": self._sku_from_url(self.url),
        }

    def _name_from_title(self, soup: BeautifulSoup) -> Optional[str]:
        og_title = soup.find("meta", property="og:title")
        raw = (og_title.get("content") if og_title else None) or (
            soup.title.get_text() if soup.title else None
        )
        if not raw:
            return None

        # "Buy X Online | Carrefour KSA" -> "X".
        # Split on the pipe first: the site suffix is stable, and cutting
        # it before the regex means a product whose own name ends in
        # "Online" still matches the Buy...Online wrapper correctly.
        head = raw.split("|")[0].strip()
        match = self._TITLE_RE.match(head)
        return match.group("name") if match else (head or None)

    @classmethod
    def _sku_from_url(cls, url: str) -> Optional[str]:
        match = cls._SKU_RE.search(url)
        return match.group(1) if match else None