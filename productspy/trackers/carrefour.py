import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
from productspy.exceptions import FetchError

class CarrefourTracker:
    def __init__(self, url: str):
        self.url = url
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        }

    def fetch_info(self):
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise FetchError(f"Failed to load Carrefour page: {e}")

        soup = BeautifulSoup(response.text, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        product_data = None

        for script in scripts:
            try:
                content = script.string
                if not content:
                    continue
                data = json.loads(content.strip())

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            product_data = item
                            break
                elif isinstance(data, dict) and data.get("@type") == "Product":
                    product_data = data
                    break
            except json.JSONDecodeError:
                continue

        if not product_data:
            raise FetchError("No product data found in JSON-LD.")

        name = product_data.get("name")
        offers = product_data.get("offers", {})
        price = offers.get("price")
        currency = offers.get("priceCurrency", "SAR")

        if not name:
            raise FetchError("Failed to extract product name.")
        if not price:
            raise FetchError("Failed to extract product price.")

        return {
            "name": name,
            "price": f"{price} {currency}",
            "url": unquote(self.url),
            "site": "Carrefour"
        }
