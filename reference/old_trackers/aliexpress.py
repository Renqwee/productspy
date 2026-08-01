import json
from typing import Optional, Dict
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from productspy.exceptions import FetchError
from productspy.utils.cookies_manager import load_cookies, save_cookies, update_cookies_interactively

class AliExpressTracker:
    PLATFORM_NAME = "aliexpress"
    PLATFORM_URL = "https://ar.aliexpress.com"

    def __init__(self, url: str):
        self.url = url

    def fetch_info(self) -> Dict[str, Optional[str]]:
        cookies = load_cookies(self.PLATFORM_NAME)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()

                if cookies:
                    context.add_cookies(cookies)

                page = context.new_page()

                try:
                    page.goto(self.url, wait_until="networkidle", timeout=30000)
                except PlaywrightTimeoutError:
                    raise FetchError("Timeout while loading page. You might need to update cookies.")

                scripts = page.query_selector_all('script[type="application/ld+json"]')
                product_data = None

                for script in scripts:
                    try:
                        content = script.inner_text()
                        data = json.loads(content)
                        if isinstance(data, list):
                            for entry in data:
                                if entry.get("@type") == "Product":
                                    product_data = entry
                                    break
                        elif isinstance(data, dict) and data.get("@type") == "Product":
                            product_data = data
                            break
                    except json.JSONDecodeError:
                        continue

                if not product_data:
                    raise FetchError("Failed to find product data in the script.")

                name = product_data.get("name")
                offers = product_data.get("offers", {})
                price = offers.get("price")
                currency = offers.get("priceCurrency")
                full_price = f"{price} {currency}" if price and currency else None

                context.close()
                browser.close()

                return {
                    "name": name,
                    "price": full_price,
                    "url": self.url,
                    "site": "AliExpress"
                }

        except FetchError as e:
            print(f"🚨 Error: {e}")
            print("⏳ Updating cookies interactively. Please complete verification in the browser...")
            update_cookies_interactively(self.PLATFORM_URL, self.PLATFORM_NAME)

            return self._fetch_info_without_retry()

    def _fetch_info_without_retry(self) -> Dict[str, Optional[str]]:
        cookies = load_cookies(self.PLATFORM_NAME)
        if not cookies:
            raise FetchError("No cookies found after update. Please try manually.")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()
            page.goto(self.url, wait_until="networkidle", timeout=30000)

            scripts = page.query_selector_all('script[type="application/ld+json"]')
            product_data = None

            for script in scripts:
                try:
                    content = script.inner_text()
                    data = json.loads(content)
                    if isinstance(data, list):
                        for entry in data:
                            if entry.get("@type") == "Product":
                                product_data = entry
                                break
                    elif isinstance(data, dict) and data.get("@type") == "Product":
                        product_data = data
                        break
                except json.JSONDecodeError:
                    continue

            if not product_data:
                raise FetchError("Failed to find product data in the script after cookies update.")

            name = product_data.get("name")
            offers = product_data.get("offers", {})
            price = offers.get("price")
            currency = offers.get("priceCurrency")
            full_price = f"{price} {currency}" if price and currency else None

            context.close()
            browser.close()

            return {
                "name": name,
                "price": full_price,
                "url": self.url
            }
