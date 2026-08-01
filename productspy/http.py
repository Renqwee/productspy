from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from .exceptions import FetchError, BlockedError

DEFAULT_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

# The site is refusing us, not failing
BLOCK_CODES = frozenset({403, 429, 503})

# Transient server faults — worth retrying, not a block
RETRY_CODES = frozenset({500, 502, 504})


@dataclass
class FetchConfig:
    timeout: float = 15.0
    max_retries: int = 3
    backoff_factor: float = 0.8
    min_delay: float = 1.0
    jitter: float = 0.4
    proxies: Sequence[str] = field(default_factory=tuple)
    user_agents: Sequence[str] = DEFAULT_USER_AGENTS
    extra_headers: dict[str, str] = field(default_factory=dict)
    verify_ssl: bool = True
    impersonate: str = "chrome"


class Fetcher:
    def __init__(self, config: Optional[FetchConfig] = None):
        self.config = config or FetchConfig()
        self._lock = threading.Lock()
        self._last_hit: dict[str, float] = {}
        self._proxy_index = 0
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        """curl_cffi replicates Chrome's TLS/HTTP2 fingerprint.

        Plain `requests` gets silently stalled or RST by sites that
        fingerprint the handshake (Noon does exactly this).
        """
        return requests.Session(impersonate=self.config.impersonate)

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.config.backoff_factor * (2 ** attempt)
        time.sleep(delay + random.uniform(0, self.config.jitter))

    def _next_proxy(self) -> Optional[dict[str, str]]:
        if not self.config.proxies:
            return None
        with self._lock:
            proxy = self.config.proxies[self._proxy_index % len(self.config.proxies)]
            self._proxy_index += 1
        return {"http": proxy, "https": proxy}

    def _throttle(self, host: str) -> None:
        with self._lock:
            last = self._last_hit.get(host, 0.0)
            wait = self.config.min_delay - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, self.config.jitter))
        with self._lock:
            self._last_hit[host] = time.monotonic()

    def headers(self, accept_language: str = "en-US,en;q=0.9") -> dict[str, str]:
        base = {
            "User-Agent": random.choice(self.config.user_agents),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }
        base.update(self.config.extra_headers)
        return base

    def get(
        self,
        url: str,
        *,
        accept_language: str = "en-US,en;q=0.9",
        headers: Optional[dict[str, str]] = None,
        **kwargs,
    ) -> requests.Response:
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        merged = self.headers(accept_language)
        if headers:
            merged.update(headers)
        timeout = kwargs.pop("timeout", self.config.timeout)

        last_error: Optional[Exception] = None

        for attempt in range(self.config.max_retries + 1):
            self._throttle(host)
            try:
                response = self._session.get(
                    url,
                    headers=merged,
                    timeout=timeout,
                    proxies=self._next_proxy(),
                    verify=self.config.verify_ssl,
                    **kwargs,
                )
            except RequestException as exc:
                # A stalled or reset connection to a live site is a soft
                # block, not a network fault — surface it as BlockedError
                # so callers know to rotate, not to mark the item broken.
                last_error = exc
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise BlockedError(
                    f"{host} did not complete the request after "
                    f"{self.config.max_retries + 1} attempts "
                    f"(stalled or reset connection): {exc}"
                ) from exc

            if response.status_code in BLOCK_CODES:
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise BlockedError(
                    f"{host} returned {response.status_code} — likely IP/bot block."
                )

            if response.status_code in RETRY_CODES:
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise FetchError(f"{host} returned HTTP {response.status_code}.")

            if not response.ok:
                raise FetchError(f"{host} returned HTTP {response.status_code}.")

            return response

        raise FetchError(f"Request to {host} failed: {last_error}")

    def resolve(self, url: str) -> str:
        """Follow short-link redirects without downloading the body."""
        try:
            response = self._session.head(
                url,
                allow_redirects=True,
                timeout=self.config.timeout,
                headers=self.headers(),
                proxies=self._next_proxy(),
            )
            return response.url
        except RequestException:
            return url

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


_default_fetcher: Optional[Fetcher] = None
_default_lock = threading.Lock()


def get_default_fetcher() -> Fetcher:
    global _default_fetcher
    with _default_lock:
        if _default_fetcher is None:
            _default_fetcher = Fetcher()
        return _default_fetcher


def configure(config: FetchConfig) -> Fetcher:
    """Swap the process-wide fetcher — this is where proxies get plugged in."""
    global _default_fetcher
    with _default_lock:
        if _default_fetcher is not None:
            _default_fetcher.close()
        _default_fetcher = Fetcher(config)
        return _default_fetcher