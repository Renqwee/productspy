from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..base import BaseTracker
from ..registry import register
from ..utils.url_tools import canonical_url

# The numeric item number (رقم الصنف) is the last dash-separated field of the
# slug on every PDP seen, in both language paths:
#   /asus-zenbook-14-laptops-648717.html
#   /sa-en/apple-iphone-15-pro-max-renewed-smartphones-628106.html
# Anchored on the end so the "14" in "zenbook-14-laptops" cannot win.
_URL_SKU_RE = re.compile(r"-(\d+)\.html$")

_STATE_MARKER = "window.__INITIAL_STATE__="
_DECODER = json.JSONDecoder()


@register("jarir.com")
class JarirTracker(BaseTracker):
    """Jarir Bookstore (jarir.com) — JSON-LD for the price, app state for
    the strikethrough and the stock detail.

    Verified live on 2026-08-03 against the three reference pages, in both
    language paths (five fetches in total):

      648717  Asus Zenbook 14   5499 SAR, was 5999, -8%   not sold online
      628106  iPhone 15 Pro Max 3199 SAR, was 5699, -43%  renewed, in stock
      566474  HP Renew backpack  249 SAR, no discount,    in stock

    **offers.price is the selling price.** Measured, not assumed, and
    measured on pages that carry a discount — an undiscounted page agrees
    under every reading and proves nothing, so 648717 and 628106 are the
    anchors here. JSON-LD said 5499.00 and 3199.00 while the pages showed
    5,499 marked down from 5,999 and 3,199 from 5,699. So neither of the
    two traps this library has already hit applies: not Carrefour's, where
    offers.price carried the discount amount, and not Extra's, where the
    pre-discount price hides behind a field named `discountPrice`.

    Three ld+json blocks per page, all `@context`/`@graph`: two identical
    BreadcrumbLists first, then the Product. name, price, currency,
    availability, image and sku all come from it and all matched the page.

    `list_price` does not: **zero occurrences of priceSpecification** on
    any of the five pages, so `list_price_from_json_ld` returns None by
    construction rather than by circumstance. It comes from the app state
    instead (see `_from_state`).

    jarir.com is a .com quoting SAR only, so default_currency is set
    explicitly rather than derived from the TLD (which would say USD).
    """

    site_name = "Jarir"
    default_currency = "SAR"
    accept_language = "ar-SA,ar;q=0.9,en;q=0.8"

    # ---- URL handling -------------------------------------------------

    def normalize_url(self, url: str) -> str:
        """Drop the query string, keep the path exactly as given.

        The three reference URLs carry no query at all, and no param has
        been found that selects a variant — Jarir gives each colour and
        capacity its own item number and its own URL. **Not verified**:
        that no such param exists. If one turns up, it belongs in a
        keep_params tuple here, the way Carrefour keeps `sid`.

        The `/sa-en/` prefix is **deliberately left alone**, and that is a
        judgement call rather than an oversight. It is a language mirror:
        `/sa-en/<slug>.html` and `/<slug>.html` are the same item number
        with the same numbers — regular_price, final_price,
        promotion_value, is_stock_available and available_shr all matched
        across both paths on 648717 and 628106. Only `name` changes, and
        the English page declares *itself* canonical, so the store treats
        them as two pages rather than one. Collapsing them would tidy the
        bot's row count at the cost of silently switching the tracked
        name's language on whoever pasted the English link — a nuisance
        traded for a surprise. A caller that wants one row per product can
        strip the prefix itself.

        Accept-Language does not decide this: the Arabic path served
        `lang="ar"` and the Arabic name under `en-US`, `en-SA` and `ar-SA`
        alike. The path is the only switch.
        """
        return canonical_url(url)

    # ---- parsing ------------------------------------------------------

    def parse(self, soup: BeautifulSoup, html: str) -> dict[str, Any]:
        data: dict[str, Any] = {}

        product = self.find_json_ld_product(soup)
        if product:
            data = self.from_json_ld(product)
            if data.get("price") is not None:
                data["price_source"] = "json-ld"
            if data.get("in_stock") is not None:
                data["in_stock_source"] = "json-ld availability"
            # Kept for the day Jarir starts emitting one; today it is
            # None on every page, and the app state is the real source.
            data["list_price"] = self.list_price_from_json_ld(product)

        sku = data.get("sku") or self._sku_from_url(self.url)
        state = self._from_state(html, sku)

        if state:
            # Fill holes first, then take the fields only the app state
            # has. JSON-LD stays authoritative wherever it produced a
            # value — same rule as Extra.
            for key, value in state.items():
                if data.get(key) in (None, ""):
                    data[key] = value

        self._drop_non_offer_list_price(data)
        return data

    @staticmethod
    def _drop_non_offer_list_price(data: dict[str, Any]) -> None:
        """A list price at or below the selling price is not an offer.

        Live on 566474: regular_price and final_price are both 249, so
        the raw field would report "was 249, now 249" on an item that has
        never been discounted. discount_pct already returns None there;
        this stops the raw field from claiming an offer anyway. The same
        guard Carrefour and Extra both needed.
        """
        raw_list, raw_price = data.get("list_price"), data.get("price")
        if raw_list is None or raw_price is None:
            return
        try:
            if Decimal(str(raw_list)) <= Decimal(str(raw_price)):
                data["list_price"] = None
                data.pop("list_price_source", None)
        except (InvalidOperation, ValueError):
            data["list_price"] = None
            data.pop("list_price_source", None)

    # ---- app state ----------------------------------------------------

    @classmethod
    def _from_state(cls, html: str, sku: Optional[str]) -> dict[str, Any]:
        """Strikethrough price and stock detail out of __INITIAL_STATE__.

        Jarir ships one `window.__INITIAL_STATE__` assignment carrying the
        whole Vuex store — 1.5 to 2.4 MB of **strict JSON**, which parsed
        cleanly with json on all five pages. That is what makes this the
        one store so far where no character window is needed: the product
        sits at a fixed address, `product.current`, and carries its own
        `sku`, so the number is tied to the page by an identity check
        instead of by proximity. Extra's dataLayer, by contrast, is JS
        literals that json.loads rejects outright.

        The script does not end at the object — a self-removing IIFE
        follows it:

            window.__INITIAL_STATE__={...};(function(){var s;...}());

        so `json.loads` on the script body fails with "Extra data" every
        time. raw_decode stops at the end of the first value, which both
        fixes that and avoids scanning two megabytes character by
        character (13 ms against 90 ms for a brace counter).

        Everything here is skipped when the sku does not match: a state
        blob for some other product is not a source, it is a wrong number
        waiting to be recorded.
        """
        current = cls._state_product(html)
        if not isinstance(current, dict):
            return {}
        state_sku = current.get("sku")
        if sku and state_sku is not None and str(state_sku) != str(sku):
            return {}

        out: dict[str, Any] = {}

        # regular_price is the advertised pre-discount price. On both
        # discounted pages it matched the strikethrough exactly (5999 and
        # 5699) and promotion_value — Jarir's own "وفّر: 500ر.س." figure —
        # closed the arithmetic: 5499 + 500 and 3199 + 2500. The sibling
        # key `price` held the same number on all three, but regular_price
        # is the one whose name says what it is.
        regular = current.get("regular_price")
        if regular is not None:
            out["list_price"] = regular
            out["list_price_source"] = "app-state product.current.regular_price"

        # Fallbacks, used only when JSON-LD went missing. final_price is
        # the selling price on all five pages, agreeing with offers.price
        # to the riyal.
        final = current.get("final_price")
        if final is not None:
            out["price"] = final
            out["price_source"] = "app-state product.current.final_price"
        if current.get("name"):
            out["name"] = current["name"]

        # ---- the two identifiers -------------------------------------
        #
        # Settled by the page, not by preference. The markup puts
        # itemprop="sku" on the numeric item number:
        #
        #   رقم الصنف <b itemprop="sku">648717</b>
        #   رقم المنتج <b>UX3405CAP060W</b>
        #
        # JSON-LD agrees ("sku": "648717"), the app state calls the
        # alphanumeric one `mpn`, and only the numeric one appears in the
        # URL. So sku is the item number and the manufacturer code rides
        # along in raw — which is also why from_json_ld's
        # `sku or mpn` fallback never fires here.
        if current.get("mpn"):
            out["mpn"] = current["mpn"]

        out.update(cls._stock_from_state(current))
        return out

    @staticmethod
    def _stock_from_state(current: dict[str, Any]) -> dict[str, Any]:
        """Jarir's two availability axes, and the field that lies.

        `stock.stock_status` and `stock.is_in_stock` read 0 / false on all
        five pages, including the two that are in stock and selling. They
        are template defaults, not state — read either one and every Jarir
        product is permanently out of stock.

        The two that do discriminate:

            is_stock_available  1 / 1 / 0   can it be bought online
            available_shr       list of showroom codes that hold it

        648717 is 0 with an empty showroom list, and JSON-LD independently
        says OutOfStock. 628106 is 1 with exactly one showroom (which is
        why the page offers delivery but no pickup at the branch the
        visitor is on), 566474 is 1 with a long list.

        **`in_stock = False` on 648717 is the right reading**, and it is
        the store's own: Jarir declares schema.org/OutOfStock and sets its
        own online flag to 0. This is not Amazon's `location_blocked`,
        which marks an item that *is* being sold where only our delivery
        address was refused — nothing about us was refused here, the item
        simply cannot be bought. Nor is the page's "الرجاء التحقّق من
        التوفر في المعارض" a claim that a showroom has it: available_shr
        is empty on that product. It is a generic call to action, so it is
        not treated as a second stock signal.

        Both flags are exported so a caller can see them disagree. They
        never did across five fetches; if they ever do, that is worth
        knowing rather than worth resolving silently here.
        """
        out: dict[str, Any] = {}

        online = current.get("is_stock_available")
        if online is not None:
            out["online_stock"] = bool(online)
            # Only used when JSON-LD did not state availability — parse()
            # fills holes and never overwrites.
            out["in_stock"] = bool(online)
            out["in_stock_source"] = "app-state is_stock_available"

        showrooms = current.get("available_shr")
        if isinstance(showrooms, list):
            out["showroom_codes"] = showrooms
            out["in_showroom"] = bool(showrooms)

        return out

    @classmethod
    def _state_product(cls, html: str) -> Optional[dict[str, Any]]:
        start = html.find(_STATE_MARKER)
        if start == -1:
            return None
        brace = html.find("{", start + len(_STATE_MARKER))
        if brace == -1:
            return None
        try:
            state, _ = _DECODER.raw_decode(html, brace)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(state, dict):
            return None
        product = state.get("product")
        if not isinstance(product, dict):
            return None
        current = product.get("current")
        return current if isinstance(current, dict) else None

    @staticmethod
    def _sku_from_url(url: str) -> Optional[str]:
        match = _URL_SKU_RE.search(url)
        return match.group(1) if match else None
