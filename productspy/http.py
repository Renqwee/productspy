from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Any, Optional, Sequence

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

# --- transport-level failure classification --------------------------
#
# Not every curl failure is a block. The distinction that matters:
# did the TCP/TLS connection ever come up?
#
#   never came up  -> the site did not even see us. DNS is wrong, the
#                     host is down, the URL is malformed, our proxy is
#                     dead. Rotating a proxy will not fix any of these,
#                     so this must NOT be a BlockedError.
#   came up, died  -> handshake completed and then the peer reset the
#                     stream, sent nothing, or stalled until timeout.
#                     That is exactly what TLS-fingerprint rejection
#                     looks like from the client side -> BlockedError.
#
# libcurl error codes (CURLE_*):
HARD_CURL_CODES = frozenset({
    1,   # UNSUPPORTED_PROTOCOL
    3,   # URL_MALFORMAT
    4,   # NOT_BUILT_IN
    5,   # COULDNT_RESOLVE_PROXY
    6,   # COULDNT_RESOLVE_HOST
    7,   # COULDNT_CONNECT
    51,  # PEER_FAILED_VERIFICATION
    60,  # SSL_CACERT
    77,  # SSL_CACERT_BADFILE
    97,  # PROXY
})
SOFT_CURL_CODES = frozenset({
    16,  # HTTP2
    28,  # OPERATION_TIMEDOUT
    35,  # SSL_CONNECT_ERROR
    52,  # GOT_NOTHING           — connected, empty reply
    55,  # SEND_ERROR
    56,  # RECV_ERROR            — connection reset mid-response
    92,  # HTTP2_STREAM
    95,  # HTTP3
})


def classify_transport_error(exc: BaseException) -> str:
    """'soft' (looks like a block) or 'hard' (connection never happened).

    Reads the libcurl code first because it is stable across curl_cffi
    versions; falls back to the exception class name when the code is
    missing. Anything unrecognised is treated as hard: claiming a block
    we cannot prove is what sends the caller off rotating proxies for
    nothing.
    """
    code = getattr(exc, "code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None

    if code in SOFT_CURL_CODES:
        return "soft"
    if code in HARD_CURL_CODES:
        return "hard"

    name = type(exc).__name__.lower()
    if "timeout" in name and "connect" not in name:
        return "soft"
    if any(k in name for k in ("dns", "proxy", "connectionerror",
                               "certificate", "invalidurl", "schema")):
        return "hard"
    return "hard"


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
        validator: Optional[Callable[[str], bool]] = None,
        **kwargs,
    ) -> requests.Response:
        """Fetch a URL, retrying transport failures and blocks.

        `validator` receives the response body and answers one question:
        is this the page we asked for? Some sites answer 200 with a
        complete-looking document that is missing the content entirely —
        Amazon serves a stripped shell for roughly a third of requests,
        with no captcha, no error code, nothing to distinguish it at the
        transport level. Retrying fixes it, so it belongs in the retry
        loop rather than in the caller.

        The callback takes text and returns a bool, so this layer still
        does not parse HTML and still knows nothing about any store.
        """
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        merged = self.headers(accept_language)
        if headers:
            merged.update(headers)
        timeout = kwargs.pop("timeout", self.config.timeout)

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
                kind = classify_transport_error(exc)
                if kind == "hard":
                    # DNS failure, refused connection, dead proxy, bad
                    # URL. The site never saw the request, so retrying
                    # and proxy rotation are both pointless — fail fast
                    # and let the caller mark the item, not the network.
                    raise FetchError(
                        f"could not reach {host}: {exc}"
                    ) from exc
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise BlockedError(
                    f"{host} accepted the connection then dropped it after "
                    f"{self.config.max_retries + 1} attempts "
                    f"(stalled or reset): {exc}"
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

            # ── الجديد ────────────────────────────────────────────────
            # 200 وجسم سليم، لكن المحتوى ناقص. BlockedError لا ParseError:
            # المعنى "أعد المحاولة وبدّل بروكسي" لا "الموقع غيّر تصميمه".
            # والتقاطه هنا يعيد استخدام backoff و throttle وتدوير
            # البروكسيات الموجودة بدل ما نكرر حلقة إعادة محاولة فوق.
            if validator is not None and not validator(response.text):
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise BlockedError(
                    f"{host} returned HTTP {response.status_code} with a body "
                    f"that failed the caller's completeness check after "
                    f"{self.config.max_retries + 1} attempts. Transport is "
                    f"healthy; the site is serving a stripped page."
                )
            
            return response

        raise FetchError(f"Request to {host} failed after all retries.")

    def post(
        self,
        url: str,
        *,
        data: Any = None,
        json: Any = None,
        accept_language: str = "en-US,en;q=0.9",
        headers: Optional[dict[str, str]] = None,
        **kwargs,
    ) -> requests.Response:
        """POST on the shared session, with throttling but no retries.

        Deliberately not retried. `get` is idempotent so replaying it is
        free; a POST changes state on the far side, and replaying one
        blindly after an ambiguous failure is how you end up applying an
        action twice. A caller that knows its POST is safe to repeat can
        loop itself.

        Shares `self._session`, which is the whole point: the response
        sets session cookies that later GETs must carry.
        """
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        merged = self.headers(accept_language)
        if headers:
            merged.update(headers)
        timeout = kwargs.pop("timeout", self.config.timeout)

        self._throttle(host)
        try:
            return self._session.post(
                url,
                data=data,
                json=json,
                headers=merged,
                timeout=timeout,
                proxies=self._next_proxy(),
                verify=self.config.verify_ssl,
                **kwargs,
            )
        except RequestException as exc:
            if classify_transport_error(exc) == "hard":
                raise FetchError(f"could not reach {host}: {exc}") from exc
            raise BlockedError(f"{host} dropped a POST to {url}: {exc}") from exc
        
    def resolve(self, url: str) -> str:
        """Follow short-link redirects.

        HEAD first because it costs no body. Amazon and AliExpress
        shorteners answer HEAD with 405/403 fairly often, and returning
        the unresolved link there means extract_asin() later fails with
        a confusing error — so fall back to a real GET before giving up.
        """
        try:
            response = self._session.head(
                url,
                allow_redirects=True,
                timeout=self.config.timeout,
                headers=self.headers(),
                proxies=self._next_proxy(),
            )
            if response.ok and response.url:
                return response.url
        except RequestException:
            pass

        try:
            response = self._session.get(
                url,
                allow_redirects=True,
                timeout=self.config.timeout,
                headers=self.headers(),
                proxies=self._next_proxy(),
            )
            return response.url or url
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
    """Swap the process-wide fetcher — this is where proxies get plugged in.

    The public entry point is productspy.configure(), which also accepts
    plain keyword arguments.
    """
    global _default_fetcher
    with _default_lock:
        if _default_fetcher is not None:
            _default_fetcher.close()
        _default_fetcher = Fetcher(config)
        return _default_fetcher