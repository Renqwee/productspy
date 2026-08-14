"""Nahdi tracker — nahdionline.com.

Verified against three live pages on 2026-08-14:

    103969818  Momcozy BM01 baby monitor   735.21 SAR, was 919.01, -20.0%
    103969826  Momcozy monitor (larger)   1103.21 SAR, was 1379.01, -20.0%
    104038610  Ninja Creami NC701UK       1699.00 SAR, was 1898.65, -10.5%

Three findings shape this file.

1. **The store is nahdionline.com, not nahdi.sa.** nahdi.sa answers HTTP
   500 on every path tried (/, /ar, /sa-ar); it is the clinics' brand
   site, not the shop. nahdionline.com redirects to /ar-sa.

2. **There is no offers.price at all.** The Product block carries an
   AggregateOffer holding lowPrice and highPrice and nothing else, so
   from_json_ld reaches lowPrice through its price-is-None fallback and
   happens to land on the right number. That is luck, not design, and
   _price_pair below states the mapping instead of inheriting it.

3. **Prices are VAT-inclusive, and the payload carries the net ones right
   beside them.** The RSC flight blob for 103969818 reads:

       "price_net":799.14, "price":919.01,
       "price_after_discount_net":639.31, "price_after_discount":735.21

   639.31 x 1.15 = 735.21 and 799.14 x 1.15 = 919.01. The _net twins are
   the same amounts before 15% VAT, so a pattern that matched "price"
   loosely would track a number 13% under what the customer pays. This
   file never reads the flight payload — JSON-LD carries everything —
   and that is the reason to keep it that way.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url

#: /ar-sa/<anything>/pdp/100023285 — **the middle segment is ignored by
#: the server**, and the id after /pdp/ is the whole identity. Measured
#: both ways: /ar-sa/100023285/pdp/100023285 redirects to the slug form
#: .../skinoren-cream-30-gm/pdp/100023285, and /ar-sa/any-slug-at-all/
#: pdp/103969818 redirects back to the numeric one. Nahdi picks the
#: canonical middle itself, so we must not key on it.
_PDP = re.compile(
    r"/(?P<locale>[a-z]{2}-[a-z]{2})/(?P<slug>[^/?#]+)/pdp/(?P<sku>\d{4,})", re.I
)


@register("nahdionline.com")
class NahdiTracker(BaseTracker):
    site_name = "Nahdi"
    # Stated rather than derived: the domain is .com and currency_from_domain
    # would say USD. Nahdi quotes SAR on the Saudi storefront.
    default_currency = "SAR"
    accept_language = "ar-SA,ar;q=0.9,en;q=0.8"

    def normalize_url(self, url: str) -> str:
        """Rebuild from the id, dropping the query and the slug.

        One product reaches us under two shapes — Nahdi links discounted
        items by number (/ar-sa/103969818/pdp/103969818) and others by
        slug (/ar-sa/skinoren-cream-30-gm/pdp/100023285) — and the server
        treats **any** middle segment as the same page. Keeping it means
        the same cream arrives from a search link and from a shared link
        as two tracked products, each with its own price history and its
        own duplicate alert. That is Noon's ?o= lesson in a different
        costume.

        The numeric form is the one rebuilt because it is derivable from
        the id alone; the server redirects it to whichever middle it
        prefers, which is its business, not ours.

        **The locale is deliberately kept**, on the Jarir precedent: /ar-sa/
        and /en-sa/ are language mirrors of one item, and folding them would
        silently flip the tracked name's language for whoever pasted the
        other link. Saving a row is not worth surprising them.

        Not verified: whether any parameter selects a variant. The
        reference URLs carry none, and Nahdi gives each variant its own
        numeric id, so the whole query is dropped on that assumption. If
        one turns up, it belongs in a keep-list here, the way ?sid= does
        for Carrefour.
        """
        match = _PDP.search(url)
        if not match:
            return canonical_url(url)
        locale = match.group("locale").lower()
        sku = match.group("sku")
        return f"https://www.nahdionline.com/{locale}/{sku}/pdp/{sku}"

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        product = self.find_json_ld_product(soup)
        if not product:
            return {}

        data = self.from_json_ld(product)
        price, list_price = _price_pair(product)
        if price is not None:
            data["price"] = price
        # list_price_from_json_ld returns None here by construction, not by
        # circumstance: there is not a single priceSpecification on any of
        # the three reference pages. Same as Extra and Jarir.
        if list_price is not None:
            data["list_price"] = list_price

        data["sku"] = data.get("sku") or _sku_from_url(self.url)
        data["locale"] = _locale_from_url(self.url)
        # Kept because the whole lowPrice mapping rests on this being 1 —
        # see _price_pair. A caller watching for it sees the day the
        # assumption stops holding.
        data["offer_count"] = self._first_offer(product).get("offerCount")
        return data


def _price_pair(product: dict[str, Any]) -> tuple[Any, Optional[Any]]:
    """(selling price, struck-through price) out of the AggregateOffer.

    **lowPrice is what you pay and highPrice is what it was.** Measured,
    not assumed, and measured on a page carrying a discount — a full-price
    page reads the same under either mapping and proves nothing. On
    103969818 the rendered page shows 735.21 in the price slot, 919.01 in
    a line-through span, and a badge reading "وفر 20 %"; (919.01-735.21)
    / 919.01 = 20.0%, matching the badge to the tenth.

    The schema.org meaning of these two fields is the cheapest and dearest
    of several **offers**, which is not what Nahdi is doing: offerCount is
    1 on all three pages. So the naming agrees with us by coincidence. If
    Nahdi ever lists real multi-seller offers, lowPrice becomes the
    cheapest seller and this mapping turns into Carrefour's bug — a number
    that is wrong but stable, which alerts once and then lies quietly.
    offer_count is kept in raw so that day is visible rather than silent.

    **A page without a discount changes offer type outright**, which is
    neither of the two shapes guessed at first. 100023285 (Skinoren cream,
    32.70 SAR, no discount) ships:

        {"@type": "Offer", ..., "price": 32.7}

    — a plain Offer with `price` and no lowPrice/highPrice at all, rather
    than an AggregateOffer with the two fields equal. So the offer type
    tracks whether a discount exists, and both branches below are live
    paths, not one path and one contingency.
    """
    offers = BaseTracker._first_offer(product)
    low = offers.get("lowPrice")
    high = offers.get("highPrice")

    if low is None:
        # The undiscounted shape: a plain Offer carrying price. Verified
        # on 100023285, where lowPrice/highPrice are both absent.
        low = offers.get("price")

    list_price = high
    # Same guard as Carrefour and Jarir: a "was" price at or below the
    # price paid is not an offer. discount_pct already returns None for it,
    # but the raw field would still claim a deal that is not there.
    if list_price is not None and low is not None:
        try:
            if float(list_price) <= float(low):
                list_price = None
        except (TypeError, ValueError):
            list_price = None

    return low, list_price


def _sku_from_url(url: str) -> Optional[str]:
    match = _PDP.search(url)
    return match.group("sku") if match else None


def _locale_from_url(url: str) -> Optional[str]:
    match = _PDP.search(url)
    return match.group("locale").lower() if match else None
