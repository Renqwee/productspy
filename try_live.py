#!/usr/bin/env python3
"""Live smoke test — hits a real store page.

    python try_live.py <product-url>
    python try_live.py <url1> <url2> ...

Prints exactly where it stopped, so a failure tells you *which* layer
broke: transport, JSON-LD lookup, field mapping, or price parsing.
"""

import sys
import traceback

import productspy as ps
from productspy.http import get_default_fetcher
from productspy.base import BaseTracker
from productspy.registry import resolve_tracker
from productspy.utils.url_tools import extract_domain

from bs4 import BeautifulSoup


def line(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def diagnose(url: str) -> None:
    line(f"URL: {url}")

    # --- 1. routing -------------------------------------------------
    domain = extract_domain(url)
    print(f"domain      : {domain}")
    try:
        tracker_cls = resolve_tracker(domain)
        print(f"tracker     : {tracker_cls.__name__} (site_name={tracker_cls.site_name})")
    except ps.UnsupportedSiteError as exc:
        print(f"FAILED at routing: {exc}")
        return

    # --- 2. transport -----------------------------------------------
    fetcher = get_default_fetcher()
    tracker = tracker_cls(url, fetcher=fetcher)
    print(f"normalized  : {tracker.url}")
    print(f"lang header : {tracker.accept_language}")

    try:
        response = fetcher.get(tracker.url, accept_language=tracker.accept_language)
    except ps.BlockedError as exc:
        print(f"FAILED at transport — BLOCKED: {exc}")
        print("  -> TLS fingerprint or IP refused. Try another impersonate target.")
        return
    except ps.FetchError as exc:
        print(f"FAILED at transport — FETCH: {exc}")
        return

    print(f"status      : {response.status_code}")
    print(f"final url   : {response.url}")
    print(f"html size   : {len(response.text):,} bytes")

    if len(response.text) < 5000:
        print("  !! suspiciously small — likely a challenge/interstitial page")

    # --- 3. JSON-LD presence ----------------------------------------
    soup = BeautifulSoup(response.text, "html.parser")
    blocks = soup.find_all("script", type="application/ld+json")
    print(f"ld+json     : {len(blocks)} block(s) found")

    product_node = BaseTracker.find_json_ld_product(soup)
    print(f"Product node: {'yes' if product_node else 'NO'}")

    if product_node:
        mapped = BaseTracker.from_json_ld(product_node)
        print("  mapped fields:")
        for key, value in mapped.items():
            shown = str(value)
            if len(shown) > 70:
                shown = shown[:67] + "..."
            print(f"    {key:10}= {shown!r}")

    # --- 4. tracker parse -------------------------------------------
    try:
        data = tracker.parse(soup, response.text)
    except Exception:
        print("FAILED inside tracker.parse():")
        traceback.print_exc()
        return

    print(f"parse() keys: {sorted(data)}")

    # --- 5. full pipeline -------------------------------------------
    try:
        product = tracker.fetch()
    except ps.ParseError as exc:
        print(f"FAILED at parse stage: {exc}")
        return
    except Exception:
        print("FAILED unexpectedly:")
        traceback.print_exc()
        return

    line("RESULT")
    print(f"name     : {product.name}")
    print(f"price    : {product.price!r}  ({type(product.price).__name__})")
    print(f"currency : {product.currency}")
    print(f"in_stock : {product.in_stock}")
    print(f"sku      : {product.sku}")
    print(f"list      : {product.list_price!r}")
    print(f"discount : {product.discount_pct}")
    print(f"image    : {product.image}")
    print(f"site     : {product.site}")
    print(f"\nstr()    : {product}")
    print(f"to_dict(): {product.to_dict()}")

    if product.price is None:
        print("\n  !! price is None — name worked, price selector did not")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"registered sites: {sorted(ps.supported_sites())}")
        sys.exit(1)
    for target in sys.argv[1:]:
        diagnose(target)