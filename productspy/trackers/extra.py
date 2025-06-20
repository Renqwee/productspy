import re
import json
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
from urllib.parse import unquote
from productspy.exceptions import FetchError

class ExtraTracker:
    def __init__(self, url: str):
        self.url = url
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }

    def fetch_info(self) -> Dict[str, Optional[str]]:
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise FetchError(f"Failed to load Extra page: {e}")

        soup = BeautifulSoup(response.text, "html.parser")
        product_data = None

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                content = script.string
                if not content:
                    continue
                data = json.loads(content.strip())

                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            product_data = item
                            break
                elif isinstance(data, dict) and data.get("@type") == "Product":
                    product_data = data
                    break
            except json.JSONDecodeError:
                continue

        name = None
        price = None
        currency = "SAR"

        if product_data:
            name = product_data.get("name")
            price = product_data.get("offers", {}).get("price")
            currency = product_data.get("offers", {}).get("priceCurrency", "SAR")

        if not price:
            scripts = soup.find_all("script")
            for script in scripts:
                if not script.string or "dataLayer.push" not in script.string:
                    continue
                try:
                    match = re.search(r'dataLayer\.push\((\{.*?\})\);', script.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        ecommerce = data.get("ecommerce", {})
                        items = ecommerce.get("items", [])
                        if items:
                            item = items[0]
                            name = name or item.get("item_name")
                            price = item.get("price")
                            currency = item.get("currency", "SAR")
                            break
                except Exception:
                    continue

        if not name or not price:
            raise FetchError("Failed to extract product name or price from Extra page.")

        return {
            "name": name,
            "price": f"{price} {currency}",
            "url": unquote(self.url)
        }
