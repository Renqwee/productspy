from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url


@register("noon.com")
class NoonTracker(BaseTracker):
    site_name = "Noon"
    default_currency = "SAR"
    accept_language = "en-SA,en;q=0.9,ar;q=0.8"

    def normalize_url(self, url: str) -> str:
        """Drop every query param.

        A Noon PDP is identified entirely by its path — the /p/ segment
        after the N-code SKU. Everything in the query string is routing
        noise: ?o= is the offer/seller hint the search page attaches,
        utm_* comes from ads, and both change per visit. Keeping them
        means the same phone shared from search, from an ad and from the
        app is stored as three separate tracked products, each with its
        own price history and its own duplicate alert.

        NOT verified against a live page yet: if Noon ever needs ?o= to
        render a specific seller's price, this would silently switch the
        tracked price to the default offer. Run try_live.py on a URL
        with and without ?o= and compare before trusting it.
        """
        return canonical_url(url)

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        # Verified against a live Noon PDP: schema.org markup carries
        # name, price, currency, availability, image and SKU. No need to
        # touch the DOM or __NEXT_DATA__ (Noon no longer ships the latter).
        product = self.find_json_ld_product(soup)
        if product:
            data = self.from_json_ld(product)
            data["list_price"] = self.list_price_from_json_ld(product)
            if data.get("name") and data.get("price") is not None:
                return data

        return self._from_dom(soup)

    def _from_dom(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Fallback only — used if Noon ever drops its JSON-LD block."""
        name_tag = soup.find("h1")
        price_tag = soup.find(attrs={"data-qa": lambda v: v and "pdp-price" in v})
        return {
            "name": name_tag.get_text(strip=True) if name_tag else None,
            "price": price_tag.get_text(strip=True) if price_tag else None,
        }