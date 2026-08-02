import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Iterable, Optional

def extract_asin(url: str) -> Optional[str]:
    path = urlparse(url).path
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})",
        r"/([A-Z0-9]{10})(?:[/?]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
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