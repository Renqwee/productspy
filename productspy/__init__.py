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

__version__ = "0.3.0"

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

_SHORTENERS = ("amzn.to", "amzn.eu", "a.co", "s.click.aliexpress", "noon.to")


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
    if any(s in url for s in _SHORTENERS):
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