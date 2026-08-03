"""productspy — product name and price extraction from shopping sites."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .exceptions import (
    BlockedError,
    FetchError,
    ParseError,
    ProductSpyError,
    UnsupportedSiteError,
)
from .http import FetchConfig, Fetcher, get_default_fetcher
from .http import configure as _configure_fetcher
from .models import Product
from .registry import register, resolve_tracker, supported_sites
from .utils.url_tools import extract_domain

from . import trackers as _trackers  # noqa: F401

__version__ = "0.4.0"

__all__ = [
    "get_product_info",
    "get_many",
    "Product",
    "FetchConfig",
    "Fetcher",
    "configure",
    "get_default_fetcher",
    "register",
    "supported_sites",
    "ProductSpyError",
    "UnsupportedSiteError",
    "FetchError",
    "BlockedError",
    "ParseError",
]

# Short-link hosts. A trailing dot means "this host prefix, any TLD" —
# s.click.aliexpress is not a whole domain, the storefront's TLD follows.
_SHORTENERS = ("amzn.to", "amzn.eu", "a.co", "s.click.aliexpress.", "noon.to")


def _is_short_link(url: str) -> bool:
    """Match short-link hosts on label boundaries, never on a substring.

    `any(s in url for s in _SHORTENERS)` — what this replaced — is the
    same bug registry._pattern_matches exists to prevent, left standing
    at the public entry point. 'a.co' sits inside dat[a.co]m, meg[a.co]m
    and alf[a.co]m, and inside any path that mentions one. Every false
    hit sends resolve() out for a HEAD plus a full redirect-following
    GET on a link that never needed either.

    The boundary cuts both ways: amzn.to.attacker.net is not amzn.to.
    """
    host = (extract_domain(url) or "").lower().strip(".")
    if not host:
        # Scheme-less input ('amzn.to/abc') — urlparse files the host
        # under path, and resolve() used to get it anyway.
        host = (extract_domain("//" + url) or "").lower().strip(".")
    if not host:
        return False

    for pattern in _SHORTENERS:
        if not pattern.endswith("."):
            if host == pattern or host.endswith("." + pattern):
                return True
            continue
        stem = pattern[:-1]
        if not host.startswith(stem + "."):
            continue
        # Only a TLD may follow the stem: 'com', or a two-label suffix
        # like 'co.uk'. Anything longer is a lookalike, not a storefront.
        rest = host[len(stem) + 1:].split(".")
        if 1 <= len(rest) <= 2 and all(label.isalpha() for label in rest):
            return True
    return False


def configure(config: Optional[FetchConfig] = None, **options: Any) -> Fetcher:
    """Replace the process-wide Fetcher.

    Both forms work:
        configure(proxies=["http://p1:8080"], min_delay=2.0)
        configure(FetchConfig(proxies=[...]))

    The keyword form is what the README documents and what callers
    actually reach for; building a FetchConfig by hand is only needed
    when the config object is constructed elsewhere and passed around.
    """
    if config is not None and options:
        raise TypeError(
            "configure() takes either a FetchConfig or keyword options, not both."
        )
    return _configure_fetcher(config if config is not None else FetchConfig(**options))


def get_product_info(url: str, *, fetcher: Optional[Fetcher] = None) -> Product:
    fetcher = fetcher or get_default_fetcher()
    if _is_short_link(url):
        url = fetcher.resolve(url)
    domain = extract_domain(url)
    if not domain:
        raise UnsupportedSiteError(f"Could not parse a domain from: {url}")
    tracker_cls = resolve_tracker(domain)
    return tracker_cls(url, fetcher=fetcher).fetch()


def get_many(
    urls: Iterable[str],
    *,
    fetcher: Optional[Fetcher] = None,
    raise_on_error: bool = False,
) -> list:
    fetcher = fetcher or get_default_fetcher()
    results = []
    for url in urls:
        try:
            results.append(get_product_info(url, fetcher=fetcher))
        except ProductSpyError as exc:
            if raise_on_error:
                raise
            results.append(exc)
    return results