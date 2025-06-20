import re
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
from urllib.parse import urlparse, urlunparse, quote, unquote
from productspy.exceptions import FetchError
from productspy.utils.url_tools import extract_asin, extract_domain, resolve_short_url

class AmazonTracker:
    def __init__(self, url: str):
        resolved_url = resolve_short_url(url)
        self.url = self._sanitize_url(resolved_url)
        self.asin = extract_asin(self.url)
        self.domain = extract_domain(self.url)

        if not self.asin or not self.domain:
            raise ValueError("Invalid Amazon URL or missing ASIN.")

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": self._language_by_domain(self.domain)
        }

    def _sanitize_url(self, url: str) -> str:
        parsed = urlparse(url)
        sanitized_path = quote(parsed.path)
        return urlunparse(parsed._replace(path=sanitized_path))

    def _language_by_domain(self, domain: str) -> str:
        if domain.endswith(".sa") or domain.endswith(".ae"):
            return "ar-SA,ar;q=0.9"
        elif domain.endswith(".de"):
            return "de-DE,de;q=0.9"
        elif domain.endswith(".co.uk"):
            return "en-GB,en;q=0.9"
        elif domain.endswith(".ca"):
            return "en-CA,en;q=0.9"
        elif domain.endswith(".com"):
            return "en-US,en;q=0.9"
        return "en-US,en;q=0.9"

    def _get_currency_from_domain(self, domain: str) -> str:
        domain_currency_map = {
            "sa": "SAR",
            "ae": "AED",
            "com": "USD",
            "co.uk": "GBP",
            "de": "EUR",
            "ca": "CAD",
            "fr": "EUR",
            "in": "INR",
        }
        for key in domain_currency_map:
            if domain.endswith(key):
                return domain_currency_map[key]
        return "USD"  

    def fetch_info(self) -> Dict[str, Optional[str]]:
        try:
            response = requests.get(self.url, headers=self.headers, timeout=10)
            response.raise_for_status()
        except Exception as e:
            raise FetchError(f"Failed to load product page: {e}")

        soup = BeautifulSoup(response.text, "html.parser")
        name = self._extract_title(soup)
        price_value = self._extract_price(soup)
        currency = self._get_currency_from_domain(self.domain)

        if price_value is not None:
            price = f"{price_value} {currency}"
        else:
            price = None

        decoded_url = unquote(self.url)  

        return {
            "name": name,
            "price": price,
            "url": decoded_url,
            "site": "Amazon"
        }

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        tag = soup.select_one("#productTitle")
        return tag.text.strip() if tag else None

    def _normalize_price_string(self, text: str) -> str:
        return ''.join(ch for ch in text if (ch.isdigit() or ch == '.'))

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        selectors = [
            ("span", {"class": "a-price-whole"}),
            ("span", {"class": "a-offscreen"}),
            ("span", {"id": "priceblock_ourprice"}),
            ("span", {"id": "priceblock_dealprice"}),
            ("span", {"id": "price_inside_buybox"}),
        ]

        for tag, attrs in selectors:
            price_tag = soup.find(tag, attrs=attrs)
            if price_tag:
                price_text = price_tag.get_text(strip=True)
                price_text = price_text.replace(",", "").replace("٫", ".")
                match = re.search(r"[\d\.]+", price_text)
                if match:
                    try:
                        return float(match.group())
                    except ValueError:
                        continue
        return None
