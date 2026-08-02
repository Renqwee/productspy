# productspy

A Python library that extracts product name, price, and availability from
shopping site pages.

## How it works

Each store gets a `Fetcher` request impersonating a real Chrome TLS/HTTP2
fingerprint (via `curl_cffi`), then a per-site tracker parses the response —
JSON-LD first, falling back to DOM selectors or embedded JS state. No headless
browser, no proxy required for the sites currently supported.

## Install

```bash
pip install productspy
```

## Usage

```python
from productspy import get_product_info

product = get_product_info("https://www.noon.com/saudi-en/some-product/")

print(product.name)
print(product.price, product.currency)
print(product.in_stock)
```

`get_product_info` returns a `Product`:

```python
@dataclass(frozen=True, slots=True)
class Product:
    name: str
    price: Decimal | None
    currency: str
    url: str
    site: str
    in_stock: bool | None
    image: str | None
    sku: str | None
    list_price: Decimal | None   # original price before a discount, if any
```

Useful properties:

```python
product.has_price        # bool
product.discount_pct     # Decimal or None — e.g. Decimal("36.2")
product.cheaper_than(other_product)   # raises if currencies differ
product.to_dict()        # JSON-serializable dict
```

### URL normalisation

Trackers canonicalise the URL before fetching, so the same product arriving
with `?o=`, `?utm_source=` or `#reviews` is one tracked item, not three:

```python
from productspy.trackers.noon import NoonTracker

NoonTracker("https://www.noon.com/saudi-en/x/N123/p/?o=abc&utm_source=ads").url
# 'https://www.noon.com/saudi-en/x/N123/p/'
```

### Multiple URLs

```python
from productspy import get_many

results = get_many(urls, raise_on_error=False)
# each item is a Product, or the exception instance if that URL failed
```

### Errors

All exceptions inherit from `ProductSpyError`. The library never prints —
it raises, and your application decides what to do.

```python
from productspy import BlockedError, ParseError, UnsupportedSiteError

try:
    product = get_product_info(url)
except BlockedError:
    ...  # site refused us (403/429/CAPTCHA, or accepted the connection
         # then reset it) — rotate proxy / back off
except FetchError:
    ...  # never reached the site: DNS, refused connection, dead proxy,
         # 404, 5xx. Retrying with another proxy will not help
except ParseError:
    ...  # page loaded but expected fields weren't found — markup changed
except UnsupportedSiteError:
    ...  # no tracker registered for this domain
```

`BlockedError` is a subclass of `FetchError`, so a single `except FetchError`
still catches everything transport-related. The split exists so a price bot can
tell "rotate and retry" apart from "this URL is dead".

### Configuration

```python
from productspy import configure

configure(proxies=["http://proxy1:8080", "http://proxy2:8080"], min_delay=2.0)
```

Any `FetchConfig` field can be passed as a keyword: `timeout`, `max_retries`,
`backoff_factor`, `min_delay`, `jitter`, `proxies`, `user_agents`,
`extra_headers`, `verify_ssl`, `impersonate`. Passing a prebuilt
`configure(FetchConfig(...))` also works.

## Supported sites

| Site | Status |
|---|---|
| Noon (noon.com) | Working — verified on a live page: name, price, currency, availability, SKU, image, list price |
| Extra (extra.com) | Tracker written — JSON-LD + GTM dataLayer fallback. Unit-tested, **not yet verified against a live page** |
| Carrefour KSA (carrefourksa.com) | Working — price and list price read from the RSC flight payload; **its JSON-LD `offers.price` is the discount amount and is discarded**. `?sid=` is required and is injected when missing |
| Amazon (amazon.*) | Working — verified live on 4 products across amazon.sa,
  amazon.de and amazon.co.uk: name, price, currency, list price, availability,
  seller, image, ASIN. Pins the delivery country so the tracked price stays on
  one market |
| AliExpress | Not yet implemented — data lives in an in-page JS variable |

Adding a store is one file in `productspy/trackers/` plus a `@register()`
decorator; nothing in the core changes.

## Contribute

Feel free to open an issue or pull request.
