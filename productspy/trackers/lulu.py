"""Lulu Hypermarket tracker — gcc.luluhypermarket.com.

Verified against live pages on 2026-08-14:

    2048258 en-sa  Nesquik cereal 330g   23.99 SAR, was 27.95, -14.2%
    2048258 en-ae  the same item         20.50 AED, no discount
      39478 en-sa  Kellogg's Corn Flakes 39.95 SAR, no discount
    2677573 en-sa  Insta360 TV Mount     no price, Out of Stock

Every domain (luluhypermarket.com, lulu.sa) redirects to
gcc.luluhypermarket.com, so **country is a path segment, not a domain**:
/en-sa/, /ar-sa/, /en-ae/. The same item above is 23.99 SAR under one
and 20.50 AED under the other, with a discount in Saudi and none in the
UAE. Currency therefore cannot be a class attribute the way it is for
every other store here, and is read off the page instead.

Three traps, all of them the silent kind.

1. **Prices carry three decimal places: "23.990".** parse_price reads a
   three-digit tail as a thousands group — correctly, since 1.250 is one
   thousand two hundred fifty in the European convention it also has to
   serve — so "20.000" comes back as 20000. A twenty-riyal item stored at
   twenty thousand. The platform is Gulf-wide and the Kuwaiti and
   Bahraini dinars really do run to three decimals (1000 fils), so it
   formats every market that way, riyals included. The fix belongs here
   rather than in parse_price: this file knows its source is ISO-style
   with a dot and no grouping, so it hands over a Decimal and parse_price
   passes typed numbers through untouched.

2. **JSON-LD availability lies.** Every product page declares
   schema.org/InStock, including 2677573, which renders "Out of Stock"
   with no price at all and reports "in_stock":false in its own payload.
   Reading the schema.org field the way every other tracker here does
   would mark the entire catalogue permanently in stock. This is Jarir's
   stock_status trap inverted: there a template default read false on
   selling items, here it reads in-stock on dead ones.

3. **An out-of-stock page still ships a price of "0.00" with a null
   currency.** models.parse_price is explicitly built to keep a
   legitimate zero rather than swallow it, and base.py checks `is None`
   for the same reason, so 0.00 would sail through as a real price. A
   tracked item silently dropping to zero is the loudest possible false
   discount alert.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register

#: /en-sa/nestle-nesquik-.../p/2048258/ — locale, slug, then the id.
#: **The slug is load-bearing here**, unlike Nahdi: /en-sa/x/p/2048258/
#: answers 404, so the path cannot be rebuilt from the id alone.
_PDP = re.compile(
    r"/(?P<locale>[a-z]{2}-[a-z]{2})/(?P<slug>[^/?#]+)/p/(?P<sku>\d+)", re.I
)

#: The payload emits these four keys as one adjacent run, in this order,
#: right after the product's own "base_code". Matching them together is
#: what anchors the numbers to this product rather than to a neighbouring
#: card — Carrefour's lesson, in a store that happens not to ship priced
#: recommendation carousels today. Not relying on that.
#:
#: **Every quote is escaped**: the run lives inside a JS string literal
#: (self.__next_f.push([1,"...\"price\":\"23.990\"..."])), so the bytes on
#: the wire carry a backslash before each quote. A pattern written against
#: the pretty-printed shape matches nothing at all, and — because the
#: price also arrives via JSON-LD — fails by quietly losing the
#: struck-through price and the stock flag rather than by raising.
#: \\? accepts both, so a future unescaped copy keeps working.
#: currency_type is a **bare null** on an out-of-stock page, not a quoted
#: string, so the arm has to accept both or the whole run stops matching
#: on exactly the pages whose stock flag matters most.
_PAYLOAD = re.compile(
    r'\\?"price\\?"\s*:\s*\\?"(?P<price>[\d.]+)\\?"\s*,\s*'
    r'\\?"in_stock\\?"\s*:\s*(?P<in_stock>true|false)\s*,\s*'
    r'\\?"currency_type\\?"\s*:\s*(?:\\?"(?P<currency>\w+)\\?"|null)\s*,\s*'
    r'\\?"retail_price\\?"\s*:\s*\\?"(?P<retail>[\d.]+)\\?"'
)

#: Fallback only — the page states its own currency, and this is for when
#: it does not (the out-of-stock shape returns null). Measured: sa, ae.
#: The rest is extrapolation from the storefronts Lulu operates; check one
#: by eye before trusting a new market.
_CURRENCIES = {
    "sa": "SAR", "ae": "AED", "qa": "QAR", "kw": "KWD",
    "bh": "BHD", "om": "OMR", "in": "INR", "my": "MYR",
}


@register("luluhypermarket.com")
class LuluTracker(BaseTracker):
    site_name = "Lulu"

    def __init__(self, url: str, fetcher=None):
        super().__init__(url, fetcher=fetcher)
        match = _PDP.search(self.url)
        self.locale = match.group("locale").lower() if match else None
        country = self.locale.split("-")[1] if self.locale else None
        # Set on the instance, shadowing the class attribute every other
        # tracker uses. It has to vary per URL here, and it is only a
        # fallback: the page normally states its currency outright.
        self.default_currency: Optional[str] = _CURRENCIES.get(country or "")
        if self.locale:
            lang = self.locale.split("-")[0]
            self.accept_language = f"{self.locale},{lang};q=0.9"

    def normalize_url(self, url: str) -> str:
        """Drop the query, keep the whole path.

        Nothing is rebuilt from the id, because the slug is **not**
        decorative here: /en-sa/x/p/2048258/ returns 404. That is the
        opposite of Nahdi, where any middle segment resolves, and the
        difference is measured rather than assumed.

        A URL with no locale (/slug/p/2048258/) is left alone rather than
        being given one. It does load — the server picks a country itself
        — but which one it picks is not ours to guess, and inventing
        /en-sa/ would quietly retarget a link someone pasted for another
        market. **The risk of leaving it is real and is Amazon's**: an
        unpinned path lets the price follow where the request came from,
        so moving the bot to another host can shift the series and fire a
        phantom discount. The currency is read from the page on every
        fetch, so such a shift changes raw["currency"] instead of hiding
        — but a caller tracking one market should pass the locale in the
        URL.
        """
        base = url.split("?", 1)[0].split("#", 1)[0]
        return base

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        product = self.find_json_ld_product(soup)
        data: dict[str, Any] = self.from_json_ld(product) if product else {}

        payload = _PAYLOAD.search(html)

        # ---- availability: the payload only, never schema.org ----------
        # from_json_ld already set in_stock=True off the lying field, so
        # this overwrites rather than fills a gap.
        if payload is not None:
            data["in_stock"] = payload.group("in_stock") == "true"
            data["in_stock_source"] = "payload"
        else:
            # Nothing trustworthy left: the schema.org value is known to
            # be wrong, so None beats repeating it.
            data["in_stock"] = None
            data["in_stock_source"] = None

        # ---- price ----------------------------------------------------
        price = _decimal(data.get("price"))
        if payload is not None:
            payload_price = _decimal(payload.group("price"))
            if payload_price is not None:
                price = payload_price
        # A zero here is the out-of-stock placeholder, not a free item.
        # Dropping it costs nothing (such a page has no price to show)
        # and keeps a phantom crash-to-zero out of the series.
        if price is not None and price == 0:
            data["zero_price_dropped"] = True
            price = None
        data["price"] = price

        # ---- currency: page first, path second -------------------------
        currency = data.get("currency") or (
            payload.group("currency") if payload is not None else None
        )
        # The page spells it lowercase ("sar"); everything else in this
        # project stores ISO-4217 uppercase.
        data["currency"] = currency.upper() if currency else self.default_currency

        # ---- struck-through price --------------------------------------
        if payload is not None:
            retail = _decimal(payload.group("retail"))
            # Equal values are the no-discount shape, seen on four live
            # pages (39.950/39.950). Same guard as Carrefour and Jarir.
            if retail is not None and price is not None and retail > price:
                data["list_price"] = retail
            data["stock_field"] = payload.group("in_stock")

        data["locale"] = self.locale
        return data


def _decimal(raw: Any) -> Optional[Decimal]:
    """Read Lulu's own number format, bypassing the separator guesser.

    The source is unambiguous — a dot decimal mark, no grouping, three
    places — so there is nothing to infer, and inferring is exactly what
    turns "20.000" into twenty thousand.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
