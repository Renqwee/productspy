import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
from productspy.exceptions import FetchError
import re

class NoonTracker:
    def __init__(self, url: str):
        self.url = url

    def fetch_info(self) -> Dict[str, Optional[str]]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept-Language": "en-US,en;q=0.9"
            }

            response = requests.get(self.url, headers=headers, timeout=15)
            if response.status_code != 200:
                raise FetchError(f"Failed to load page. Status code: {response.status_code}")

            soup = BeautifulSoup(response.text, "html.parser")

            for div in soup.find_all("div"):
                class_name = div.get("class")
                if class_name:
                    text = div.get_text(strip=True)
                    if "SAR" in text or "ر.س" in text or "﷼" in text:
                        print(f"🪙 Price-like content: {text} | Class: {class_name}")

            name_tag = soup.find("h1")
            name = name_tag.get_text(strip=True) if name_tag else None

            price_tag = soup.find("div", class_=lambda x: x and ("priceNow" in x or "sellingPrice" in x))
            price = price_tag.get_text(strip=True) if price_tag else None

            if price:
                price = re.sub(r"[^\d.,]+", "", price)

            full_price = f"{price} SAR" if price else None

            if not name or not full_price:
                raise FetchError("Failed to find product name or price in HTML.")

            return {
                "name": name,
                "price": full_price,
                "url": self.url,
                "site": "Noon"
            }

        except Exception as e:
            raise FetchError(f"Failed to extract product data: {e}")
