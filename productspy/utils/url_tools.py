import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Iterable, Optional

_ISBN10_SHAPE = re.compile(r"[0-9]{9}[0-9X]$")


def _looks_like_asin(code: str) -> bool:
    """Vet a candidate id that the URL itself did not label as one.

    Two accepted shapes: B0 + eight for goods, ISBN-10 for books.

    The ISBN branch is checksum-verified, not shape-matched, because
    shape alone accepts any ten digits — a category id, an order number,
    a phone number in a slug. The check digit (sum of i * digit_i for
    i = 1..10, divisible by 11) turns that into a 1-in-11 accident.
    """
    if len(code) != 10:
        return False
    if code.startswith("B0"):
        return True
    if not _ISBN10_SHAPE.match(code):
        return False
    total = sum(i * (10 if ch == "X" else int(ch))
                for i, ch in enumerate(code, start=1))
    return total % 11 == 0


def extract_asin(url: str) -> Optional[str]:
    """Pull the ASIN out of an Amazon URL, or None.

    The first three patterns are anchored on a path segment that says
    what follows is a product id, so they take the id as given. The
    fourth has no such marker — any ten upper-case/digit segment matches
    it — so it is the only one vetted by _looks_like_asin.

    Without that check `/SMARTPHONE/ref=x` yields 'SMARTPHONE', and
    AmazonTracker.normalize_url then rebuilds /dp/SMARTPHONE, discards
    the real path and fetches a dead URL with full confidence. Returning
    None leaves the caller's URL untouched, which is the honest answer.
    """
    path = urlparse(url).path
    patterns = [
        (r"/dp/([A-Z0-9]{10})", False),
        (r"/gp/product/([A-Z0-9]{10})", False),
        (r"/product/([A-Z0-9]{10})", False),
        (r"/([A-Z0-9]{10})(?:[/?]|$)", True),
    ]
    for pattern, vetted in patterns:
        for match in re.finditer(pattern, path):
            # finditer, not search: on /SMARTPHONE/B0FWXZLD6F the first
            # hit fails the check and the real id is the second.
            if not vetted or _looks_like_asin(match.group(1)):
                return match.group(1)
    return None

def extract_domain(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return None


def canonical_url(url: str, keep_params: Iterable[str] = ()) -> str:
    """Strip the query string down to `keep_params` and drop the fragment.

    Why this exists: the bot stores one row per URL. Noon appends ?o=,
    ads append ?utm_source=, shares append #ref — so the same product
    arriving from three places becomes three tracked items with three
    separate price histories and three duplicate alerts.

    keep_params is per store: a param that selects the variant (colour,
    size, seller) must survive, anything that only identifies the
    referrer must not.
    """
    if not url:
        return url
    parsed = urlparse(url)
    keep = {p.lower() for p in keep_params}
    query = ""
    if keep:
        pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if k.lower() in keep]
        query = urlencode(pairs)
    return urlunparse(parsed._replace(query=query, fragment=""))

# Country-code TLD -> ISO currency. Used when a page states a price but
# no currency, which is common on Amazon's regional storefronts.
_TLD_CURRENCY = {
    "sa": "SAR", "ae": "AED", "eg": "EGP", "qa": "QAR", "kw": "KWD",
    "bh": "BHD", "om": "OMR", "jo": "JOD", "iq": "IQD", "lb": "LBP",
    "ma": "MAD", "dz": "DZD", "tn": "TND",
    "uk": "GBP", "de": "EUR", "fr": "EUR", "it": "EUR", "es": "EUR",
    "nl": "EUR", "be": "EUR", "ie": "EUR", "at": "EUR", "pt": "EUR",
    "fi": "EUR", "gr": "EUR",
    "se": "SEK", "no": "NOK", "dk": "DKK", "pl": "PLN", "cz": "CZK",
    "ch": "CHF", "tr": "TRY", "ru": "RUB", "ua": "UAH",
    "ca": "CAD", "mx": "MXN", "br": "BRL", "ar": "ARS", "cl": "CLP",
    "in": "INR", "jp": "JPY", "cn": "CNY", "kr": "KRW", "sg": "SGD",
    "my": "MYR", "id": "IDR", "th": "THB", "ph": "PHP", "vn": "VND",
    "au": "AUD", "nz": "NZD", "za": "ZAR", "ng": "NGN", "ke": "KES",
    "com": "USD",
}


def currency_from_domain(domain: Optional[str], default: str = "USD") -> str:
    """Best guess at a storefront's currency from its TLD.

    amazon.sa -> SAR, amazon.co.uk -> GBP, amazon.com -> USD.
    Only a fallback: a currency stated on the page always wins.
    """
    if not domain:
        return default
    parts = domain.lower().rstrip(".").split(".")
    if not parts:
        return default
    # co.uk / com.au / com.br -> the country code is the last label
    tld = parts[-1]
    return _TLD_CURRENCY.get(tld, default)