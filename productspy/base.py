from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from bs4 import BeautifulSoup

from .exceptions import ParseError
from .http import Fetcher, get_default_fetcher
from .models import Product, detect_currency, parse_price
from .utils.url_tools import currency_from_domain, extract_domain


class BaseTracker(ABC):
    """Every store tracker inherits this.

    Subclasses only implement `parse()`. Networking, throttling, proxy
    rotation and error handling all live in the shared Fetcher.
    """

    site_name: str = "Unknown"
    # None = derive from the storefront's TLD. Set it explicitly only for
    # single-market stores (noon.com serves SAR from a .com domain).
    default_currency: Optional[str] = None
    accept_language: str = "en-US,en;q=0.9"

    def __init__(self, url: str, fetcher: Optional[Fetcher] = None):
        self.fetcher = fetcher or get_default_fetcher()
        self.url = self.normalize_url(url)

    @property
    def fallback_currency(self) -> str:
        """Last resort when neither the page nor the price text says."""
        return self.default_currency or currency_from_domain(
            extract_domain(self.url)
        )

    # ---- overridable hooks -------------------------------------------

    def normalize_url(self, url: str) -> str:
        """Strip tracking params, canonicalize. Override per store."""
        return url

    @abstractmethod
    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        """Return at least {'name': ..., 'price': ...}."""

    # ---- shared extraction strategies --------------------------------

    @staticmethod
    def find_json_ld_product(soup: BeautifulSoup) -> Optional[dict[str, Any]]:
        """Most modern stores ship schema.org Product markup. This is the
        most stable extraction path — it survives redesigns.
        """
        for script in soup.find_all("script", type="application/ld+json"):
            content = script.string or script.get_text()
            if not content:
                continue
            try:
                data = json.loads(content.strip())
            except json.JSONDecodeError:
                continue
            found = BaseTracker._walk_for_product(data)
            if found:
                return found
        return None

    @staticmethod
    def _walk_for_product(node: Any, depth: int = 0) -> Optional[dict[str, Any]]:
        """JSON-LD nests Product inside @graph, arrays, or itemListElement."""
        if depth > 6:
            return None
        if isinstance(node, dict):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types:
                return node
            for key in ("@graph", "itemListElement", "mainEntity"):
                if key in node:
                    found = BaseTracker._walk_for_product(node[key], depth + 1)
                    if found:
                        return found
        elif isinstance(node, list):
            for item in node:
                found = BaseTracker._walk_for_product(item, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def find_next_data(soup: BeautifulSoup) -> Optional[dict[str, Any]]:
        """Next.js sites (Noon, many others) embed full state here."""
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag:
            return None
        try:
            return json.loads(tag.string or tag.get_text())
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def from_json_ld(data: dict[str, Any]) -> dict[str, Any]:
        """Map a schema.org Product dict onto our field names."""
        offers = data.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        availability = str(offers.get("availability", "")).lower()

        in_stock: Optional[bool] = None
        if "instock" in availability:
            in_stock = True
        elif "outofstock" in availability or "soldout" in availability:
            in_stock = False

        image = data.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        elif isinstance(image, dict):
            image = image.get("url")

        return {
            "name": data.get("name"),
            "price": offers.get("price") or offers.get("lowPrice"),
            "currency": offers.get("priceCurrency"),
            "in_stock": in_stock,
            "image": image,
            "sku": data.get("sku") or data.get("mpn"),
        }

    # ---- main entry point --------------------------------------------

    def fetch(self) -> Product:
        response = self.fetcher.get(self.url, accept_language=self.accept_language)
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        data = self.parse(soup, html)
        name = (data.get("name") or "").strip()
        if not name:
            raise ParseError(
                f"{self.site_name}: could not extract product name from {self.url}. "
                "The page layout may have changed."
            )

        raw_price = data.get("price")
        price = parse_price(raw_price)
        list_price = parse_price(data.get("list_price"))
        currency = data.get("currency") or detect_currency(
            str(raw_price), self.fallback_currency
        )

        return Product(
            name=name,
            price=price,
            currency=currency,
            url=response.url,
            site=self.site_name,
            in_stock=data.get("in_stock"),
            image=data.get("image"),
            sku=data.get("sku"),
            list_price=list_price,
            raw=data,
        )