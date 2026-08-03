from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url

# Window sizes for the SKU-anchored list-price lookup, measured on the two
# reference pages (2026-08-03) rather than borrowed from another store:
#
#   priceRange.minPrice ... 570 / 574 chars ... "amplienceMediaSet":"<sku>_800"
#   "amplienceMediaSet":"<sku>_800","discountPrice":{ ... "value": ... 15 chars
#
# Both distances were identical on both pages and on both copies of the app
# state. The next-nearest priceRange is 417,912 chars away, so these are not
# close to ambiguous — Carrefour's 2000-char window would be 3x wider than
# anything measured here.
_LIST_LOOKBEHIND = 800
_DISCOUNT_LOOKAHEAD = 120

_PRICE_RANGE_RE = re.compile(
    r'"priceRange":\{"minPrice":\{[^{}]*?"value":([0-9]+(?:\.[0-9]+)?)'
)
_DISCOUNT_PRICE_RE = re.compile(
    r'"discountPrice":\{[^{}]*?"value":([0-9]+(?:\.[0-9]+)?)'
)


@register("extra.com")
class ExtraTracker(BaseTracker):
    """eXtra (extra.com) — Saudi electronics retailer.

    extra.com is a .com that quotes SAR only, so default_currency is set
    explicitly rather than derived from the TLD (which would say USD).

    Verified live on 2026-08-03, SKUs 100462501 and 100389560:

      - Two ld+json blocks per page, BreadcrumbList and Product.
      - offers.price is the **selling** price — 549 on a product marked
        down from 619, 5699 on one with no discount. Carrefour's trap,
        where offers.price carried the discount amount, does not apply
        here; the number was compared against the page both ways round.
      - name, price, currency, in_stock, image and sku all come from
        JSON-LD and all matched the page.
      - list_price does not: there is no priceSpecification anywhere on
        either page, so it comes from the app state (below).

    **Not verified**: the dataLayer fallback has never run on a real Extra
    page. Its three payloads parse structurally — _balanced_object cut all
    of them at the right brace — but every one fails json.loads, because
    they are JS literals carrying live expressions:

        'marketplace_product_flag': pdpDetails.marketPlaceProduct === true ? 'Yes':'No',
        "page_type":"PRODUCT" || '',
        discount_price: 619 - 70 || 0,

    so _from_data_layer returns None here. It is kept for stores or page
    templates that push strict JSON, and its unit tests cover that shape
    only. Treat it as untested against reality.
    """

    site_name = "Extra"
    default_currency = "SAR"
    accept_language = "en-SA,en;q=0.9,ar;q=0.8"

    def normalize_url(self, url: str) -> str:
        return canonical_url(url)

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        data: dict[str, Any] = {}

        product = self.find_json_ld_product(soup)
        if product:
            data = self.from_json_ld(product)
            data["price_source"] = "json-ld"
            data["list_price"] = self.list_price_from_json_ld(product)
            if data["list_price"] is None:
                # Verified live: Extra ships no priceSpecification at all
                # (zero occurrences on both reference pages), so the shared
                # JSON-LD helper can never find a strikethrough here. The
                # advertised one lives in the app state instead.
                struck = self._list_price_from_app_state(
                    html, data.get("sku"), data.get("price")
                )
                if struck is not None:
                    data["list_price"] = struck
                    data["list_price_source"] = "app-state priceRange.minPrice"
            if data.get("name") and data.get("price") is not None:
                return data

        # JSON-LD missing or half-filled. Extra's pages push the same
        # product into Google Tag Manager's dataLayer, which carries the
        # price even on templates where the schema block is truncated.
        layer = self._from_data_layer(html)
        if layer:
            # Only fill the holes: JSON-LD is the more authoritative
            # source when it did produce a value.
            for key, value in layer.items():
                if data.get(key) in (None, ""):
                    data[key] = value

        return data

    # ---- list price from the app state -------------------------------

    @staticmethod
    def _list_price_from_app_state(
        html: str, sku: Any, price: Any
    ) -> Optional[str]:
        """The advertised pre-discount price, anchored on the SKU.

        Extra's own naming is inverted the way Carrefour's was, in a
        different place. Verified on SKU 100389560 (2026-08-03), which
        sells at 549 marked down from 619:

            "priceRange":{"minPrice":{...,"value":619,"priceType":"FROM"...
            "amplienceMediaSet":"100389560_800",
            "discountPrice":{...,"value":549,...},
            "percentageDiscount":{...,"value":11.3,...}

        So `discountPrice` is what you pay and the plain price is the
        pre-discount one — read them the other way round and the tracker
        reports a 619 product selling at 619, silently losing the offer.
        On the no-discount page (100462501) `discountPrice` is null and
        priceRange.minPrice is the selling price, so **presence of a
        non-null discountPrice is the only thing that makes minPrice a
        list price**. Without that test this would invent a strikethrough
        on every page that has none.

        Anchored on the SKU because a PDP also ships recommendation
        carousels, each with its own price block. The windows are the
        measured distances plus margin, not a round number.

        Returns text, not a Decimal: parse_price in the shared pipeline
        owns number parsing, and it is the layer with the separator rules.
        """
        if not sku:
            return None

        anchor = re.search(
            r'"amplienceMediaSet":"' + re.escape(str(sku)) + r'[^"]*"', html
        )
        if not anchor:
            return None

        # A null discountPrice means no offer — nothing to report.
        tail = html[anchor.end():anchor.end() + _DISCOUNT_LOOKAHEAD]
        if not _DISCOUNT_PRICE_RE.search(tail):
            return None

        head = html[max(0, anchor.start() - _LIST_LOOKBEHIND):anchor.start()]
        found = _PRICE_RANGE_RE.findall(head)
        if not found:
            return None
        candidate = found[-1]  # nearest one behind the anchor

        # A list price at or below the selling price is not an offer. The
        # same guard Carrefour needed: the raw field keeps claiming a deal
        # long after discount_pct has correctly gone quiet.
        try:
            if price is not None and Decimal(candidate) <= Decimal(str(price)):
                return None
        except InvalidOperation:
            return None
        return candidate

    # ---- dataLayer fallback ------------------------------------------

    @staticmethod
    def _from_data_layer(html: str) -> Optional[dict[str, Any]]:
        """Pull the first ecommerce item out of a dataLayer.push({...}).

        Brace-counting instead of a regex on purpose: a lazy pattern like
        r'dataLayer\\.push\\((\\{.*?\\})\\)' stops at the first '})' it
        sees, and GTM payloads routinely contain nested objects and
        strings holding braces, so the regex either truncates the JSON or
        swallows the rest of the script. The scanner below tracks string
        state and escapes, so it always ends on the brace that actually
        closes the object.
        """
        marker = "dataLayer.push("
        start = 0
        while True:
            found = html.find(marker, start)
            if found == -1:
                return None
            brace = html.find("{", found + len(marker))
            if brace == -1:
                return None
            blob = ExtraTracker._balanced_object(html, brace)
            start = found + len(marker)
            if not blob:
                continue
            try:
                payload = json.loads(blob)
            except json.JSONDecodeError:
                # GTM payloads are often JS literals, not strict JSON
                # (single quotes, unquoted keys, trailing commas). Skip
                # and try the next push rather than failing the parse.
                continue
            item = ExtraTracker._first_ecommerce_item(payload)
            if item:
                return item

    @staticmethod
    def _balanced_object(text: str, start: int) -> Optional[str]:
        """Return text[start:] up to the brace that closes text[start]."""
        depth = 0
        in_string = False
        quote = ""
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    in_string = False
                continue
            if char in ('"', "'"):
                in_string = True
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    @staticmethod
    def _first_ecommerce_item(payload: Any) -> Optional[dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        ecommerce = payload.get("ecommerce")
        if not isinstance(ecommerce, dict):
            return None

        ga4 = True
        items = ecommerce.get("items")
        if not isinstance(items, list) or not items:
            # GA3-shaped payloads: ecommerce.detail.products / .purchase
            for key in ("detail", "purchase", "add"):
                block = ecommerce.get(key)
                if isinstance(block, dict) and isinstance(block.get("products"), list):
                    items = block["products"]
                    ga4 = False
                    break
        if not isinstance(items, list) or not items:
            return None

        item = items[0]
        if not isinstance(item, dict):
            return None

        if ga4:
            # In GA4, items[].price is the unit price *before* discount and
            # items[].discount is what comes off it; ecommerce.value is what
            # the customer actually pays. Extra's own view_item push proves
            # the gap is real — value 549 alongside price 619, discount 70,
            # on a product selling at 549. Reading items[].price here would
            # inflate the tracked price by 12.7% on exactly the pages where
            # this fallback runs, which is the silent-wrong-number failure
            # the whole library is built against.
            #
            # No arithmetic reconstruction when value is missing: a price we
            # cannot read is an honest None, a price we derive from fields
            # never seen live is a guess.
            price = ecommerce.get("value")
        else:
            # GA3 has no separate value field and products[].price is the
            # selling price by that spec's convention.
            price = item.get("price")

        return {
            "name": item.get("item_name") or item.get("name"),
            "price": price,
            "currency": item.get("currency") or ecommerce.get("currencyCode"),
        }