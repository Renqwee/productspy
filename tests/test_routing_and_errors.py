"""Routing boundaries, transport-error semantics, URL canonicalisation.

The three things that were silently wrong before: a lookalike domain got
someone else's tracker, an unreachable host was reported as a block, and
the same product under two URLs was two products.
"""

import socket
import threading

import pytest

from productspy import (
    BlockedError,
    FetchError,
    UnsupportedSiteError,
    configure,
    get_product_info,
)
from productspy.http import FetchConfig, Fetcher, classify_transport_error
from productspy.registry import resolve_tracker
from productspy.trackers.amazon import AmazonTracker
from productspy.trackers.extra import ExtraTracker
from productspy.trackers.noon import NoonTracker
from productspy.utils.url_tools import canonical_url, extract_asin


# --------------------------------------------------------------------
# Routing must respect label boundaries
# --------------------------------------------------------------------

@pytest.mark.parametrize("domain", ["noon.com", "saudi.noon.com"])
def test_real_noon_domains_route_to_noon(domain):
    assert resolve_tracker(domain) is NoonTracker


@pytest.mark.parametrize(
    "domain",
    [
        "fakenoon.com",         # someone else's shop
        "noon.com.attacker.net",  # phishing host ending elsewhere
        "mynoon.com.sa",
        "extras.com",
    ],
)
def test_lookalike_domains_are_rejected(domain):
    with pytest.raises(UnsupportedSiteError):
        resolve_tracker(domain)


def test_extra_routes_to_extra():
    assert resolve_tracker("extra.com") is ExtraTracker
    assert resolve_tracker("www.extra.com".removeprefix("www.")) is ExtraTracker


# --------------------------------------------------------------------
# Transport errors: unreachable != blocked
# --------------------------------------------------------------------

@pytest.fixture
def fast_fetcher():
    return Fetcher(FetchConfig(min_delay=0, jitter=0, backoff_factor=0, max_retries=1))


def test_refused_connection_is_fetch_error_not_blocked(fast_fetcher):
    """Nothing is listening. The site never saw us — rotating a proxy
    would be wasted work, so this must not look like a block."""
    with pytest.raises(FetchError) as exc:
        fast_fetcher.get("http://127.0.0.1:1/", timeout=2)
    assert not isinstance(exc.value, BlockedError)


def test_unresolvable_host_is_fetch_error_not_blocked(fast_fetcher):
    with pytest.raises(FetchError) as exc:
        fast_fetcher.get("http://no-such-host-productspy.invalid/", timeout=3)
    assert not isinstance(exc.value, BlockedError)


def test_stalled_connection_is_blocked():
    """Accepted then never answered — the shape of a fingerprint refusal."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    held = []

    def accept_and_hold():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            held.append(conn)  # keep it open, send nothing

    threading.Thread(target=accept_and_hold, daemon=True).start()
    fetcher = Fetcher(FetchConfig(min_delay=0, jitter=0, backoff_factor=0,
                                  max_retries=0, timeout=1))
    try:
        with pytest.raises(BlockedError):
            fetcher.get(f"http://127.0.0.1:{port}/")
    finally:
        listener.close()
        for conn in held:
            conn.close()


def test_classifier_defaults_to_hard_when_code_is_unknown():
    """An unrecognised failure must not be reported as a block we
    cannot prove."""

    class _Weird(Exception):
        code = 999

    assert classify_transport_error(_Weird()) == "hard"


# --------------------------------------------------------------------
# URL canonicalisation
# --------------------------------------------------------------------

def test_noon_url_drops_tracking_params():
    same = [
        "https://www.noon.com/saudi-en/phone-x/N53442739A/p/?o=abc123",
        "https://www.noon.com/saudi-en/phone-x/N53442739A/p/?utm_source=ads&o=zzz",
        "https://www.noon.com/saudi-en/phone-x/N53442739A/p/#reviews",
    ]
    normalised = {NoonTracker(u, fetcher=object()).url for u in same}
    assert len(normalised) == 1
    assert normalised.pop() == (
        "https://www.noon.com/saudi-en/phone-x/N53442739A/p/"
    )


def test_canonical_url_can_keep_selected_params():
    kept = canonical_url("https://shop.test/p?variant=red&utm_source=x",
                         keep_params=["variant"])
    assert kept == "https://shop.test/p?variant=red"


def test_canonical_url_leaves_a_clean_url_alone():
    url = "https://www.extra.com/en-sa/product/12345/"
    assert canonical_url(url) == url


# --------------------------------------------------------------------
# extract_asin: a path segment is not an ASIN
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "url, asin",
    [
        ("https://www.amazon.sa/dp/B0FWXZLD6F", "B0FWXZLD6F"),
        ("https://www.amazon.sa/some-title/dp/B0FWXZLD6F/ref=sr_1_1", "B0FWXZLD6F"),
        ("https://www.amazon.de/gp/product/B09WVVZQD3?th=1", "B09WVVZQD3"),
        ("https://www.amazon.co.uk/product/B07TCB5DBG/", "B07TCB5DBG"),
        ("https://www.amazon.sa/B0CDL3CQHV", "B0CDL3CQHV"),
        ("https://www.amazon.sa/B0CDL3CQHV/ref=x", "B0CDL3CQHV"),
        ("https://www.amazon.com/dp/0306406152", "0306406152"),   # ISBN-10
        ("https://www.amazon.com/043935806X/", "043935806X"),     # ISBN-10, X check
    ],
)
def test_extract_asin_finds_real_identifiers(url, asin):
    assert extract_asin(url) == asin


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.sa/SMARTPHONE/ref=x",   # a word, ten characters
        "https://www.amazon.sa/HEADPHONES/",
        "https://www.amazon.sa/CATEGORIES",
        "https://www.amazon.sa/1234567890/",        # ten digits, not an ISBN-10
    ],
)
def test_extract_asin_rejects_bare_path_words(url):
    """A ten-character path segment is not an identifier.

    Nothing else guards this: normalize_url then rebuilds
    /dp/SMARTPHONE, throws the real path away and fetches a dead URL
    with full confidence.
    """
    assert extract_asin(url) is None


def test_normalize_url_keeps_a_url_it_cannot_identify():
    url = "https://www.amazon.sa/SMARTPHONE/ref=x"
    assert AmazonTracker(url, fetcher=object()).url == url


# --------------------------------------------------------------------
# Shortener detection is a routing boundary too
# --------------------------------------------------------------------

class _RecordingFetcher:
    """Stands in for a Fetcher and records what got resolved."""

    def __init__(self):
        self.resolved = []

    def resolve(self, url):
        self.resolved.append(url)
        return url


@pytest.mark.parametrize(
    "url",
    [
        "https://data.com/p/123",        # contains 'a.co' inside 'dat[a.co]m'
        "https://mega.com/x",
        "https://alfa.com/y",
        "https://example.com/a.co/page",  # in the path, not the host
        "https://amzn.to.attacker.net/x",  # lookalike host ending elsewhere
        "https://notamzn.to/x",
        "https://s.click.aliexpress.com.attacker.net/x",
    ],
)
def test_ordinary_urls_are_not_treated_as_short_links(url):
    """Each false hit costs a HEAD plus a full redirect-following GET."""
    fetcher = _RecordingFetcher()
    with pytest.raises(UnsupportedSiteError):
        get_product_info(url, fetcher=fetcher)
    assert fetcher.resolved == []


@pytest.mark.parametrize(
    "url",
    [
        "https://amzn.to/3xYzAbC",
        "https://amzn.eu/d/abc123",
        "https://a.co/d/abc123",
        "https://www.a.co/d/abc123",
        "https://s.click.aliexpress.com/e/_abc123",
        "https://noon.to/abc123",
    ],
)
def test_real_short_links_still_resolve(url):
    fetcher = _RecordingFetcher()
    with pytest.raises(UnsupportedSiteError):
        get_product_info(url, fetcher=fetcher)
    assert fetcher.resolved == [url]


# --------------------------------------------------------------------
# configure() matches its documented signature
# --------------------------------------------------------------------

def test_configure_accepts_keyword_options():
    fetcher = configure(proxies=["http://p1:8080"], min_delay=0)
    assert fetcher.config.proxies == ["http://p1:8080"]
    assert fetcher.config.min_delay == 0
    configure(FetchConfig())  # reset, and prove the object form still works


def test_configure_rejects_mixed_forms():
    with pytest.raises(TypeError):
        configure(FetchConfig(), min_delay=5)