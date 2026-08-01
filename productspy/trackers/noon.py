from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register


@register("noon.com")
class NoonTracker(BaseTracker):
    site_name = "Noon"
    default_currency = "SAR"
    accept_language = "en-SA,en;q=0.9,ar;q=0.8"

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        # Verified against a live Noon PDP: schema.org markup carries
        # name, price, currency, availability, image and SKU. No need to
        # touch the DOM or __NEXT_DATA__ (Noon no longer ships the latter).
        product = self.find_json_ld_product(soup)
        if product:
            data = self.from_json_ld(product)
            data["list_price"] = self._strikethrough_price(product)
            if data.get("name") and data.get("price") is not None:
                return data

        return self._from_dom(soup)

    @staticmethod
    def _strikethrough_price(product: dict[str, Any]) -> Any:
        """Pre-discount price, when Noon advertises one.

        Lets a tracker tell a real markdown from a raised-then-cut price.
        """
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        spec = offers.get("priceSpecification") or {}
        if isinstance(spec, list):
            spec = spec[0] if spec else {}
        if "strikethrough" in str(spec.get("priceType", "")).lower():
            return spec.get("price")
        return None

    def _from_dom(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Fallback only — used if Noon ever drops its JSON-LD block."""
        name_tag = soup.find("h1")
        price_tag = soup.find(attrs={"data-qa": lambda v: v and "pdp-price" in v})
        return {
            "name": name_tag.get_text(strip=True) if name_tag else None,
            "price": price_tag.get_text(strip=True) if price_tag else None,
        }
