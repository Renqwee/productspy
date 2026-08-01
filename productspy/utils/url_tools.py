import re
from urllib.parse import urlparse
from typing import Optional

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