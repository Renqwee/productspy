from __future__ import annotations

import json
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url


@register("extra.com")
class ExtraTracker(BaseTracker):
    """eXtra (extra.com) — Saudi electronics retailer.

    extra.com is a .com that quotes SAR only, so default_currency is set
    explicitly rather than derived from the TLD (which would say USD).
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
            data["list_price"] = self.list_price_from_json_ld(product)
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

        items = ecommerce.get("items")
        if not isinstance(items, list) or not items:
            # GA3-shaped payloads: ecommerce.detail.products / .purchase
            for key in ("detail", "purchase", "add"):
                block = ecommerce.get(key)
                if isinstance(block, dict) and isinstance(block.get("products"), list):
                    items = block["products"]
                    break
        if not isinstance(items, list) or not items:
            return None

        item = items[0]
        if not isinstance(item, dict):
            return None

        price = item.get("price")
        if price is None:
            price = item.get("value")

        return {
            "name": item.get("item_name") or item.get("name"),
            "price": price,
            "currency": item.get("currency") or ecommerce.get("currencyCode"),
        }