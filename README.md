# productspy

A Python library that extracts product name, price, and availability from
shopping site pages.

## How it works

Each store gets a `Fetcher` request impersonating a real Chrome TLS/HTTP2
fingerprint (via `curl_cffi`), then a per-site tracker parses the response —
JSON-LD where the store ships it, otherwise DOM selectors or embedded JS
state. No headless browser, no proxy required for the sites currently
supported.

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
    raw: dict                    # everything the tracker found, unmapped
    fetched_at: datetime         # UTC, set at construction
```

Useful properties:

```python
product.has_price        # bool
product.discount_pct     # Decimal or None — e.g. Decimal("36.2")
product.cheaper_than(other_product)   # raises if currencies differ
product.to_dict()        # JSON-serializable dict (drops raw)
```

`raw` carries per-store extras that have no place in the common shape —
the seller name and delivery-block flag on Amazon, the price container the
number came from, the availability wording in the storefront's own language.

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

`BlockedError` also covers a case that is not a refusal: a store answering 200
with a page that is missing its content. Amazon serves such a stripped
document for roughly a third of requests, with no captcha and nothing visible
at the transport level. Retrying fixes it, so the retry loop handles it — but
with the default `max_retries=3` a small fraction of fetches still exhaust all
four attempts and raise. Treat it as "ask again later", not as a broken URL.

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
| Carrefour KSA (carrefourksa.com) | Working — price and list price read from the RSC flight payload; **its JSON-LD `offers.price` is the discount amount and is discarded**. `?sid=` is required and is injected when missing |
| Amazon (amazon.\*) | Working — verified live on four products across amazon.sa, amazon.de and amazon.co.uk: name, price, currency, list price, availability, seller, image, ASIN. One tracker covers every storefront; the delivery country is pinned so the tracked price stays in one market |
| Extra (extra.com) | Tracker written — JSON-LD + GTM dataLayer fallback. Unit-tested, **not yet verified against a live page** |
| AliExpress | Not yet implemented — data lives in an in-page JS variable |

Adding a store is one file in `productspy/trackers/` plus a `@register()`
decorator; nothing in the core changes.

### Amazon

One tracker serves every storefront — `amazon.sa`, `amazon.de`,
`amazon.co.uk` and the rest — because the markup is shared. What is not
shared is the market, and that is where the prices go wrong if you ignore it.

Language, display currency and delivery country are three separate axes.
`Accept-Language` sets the page language *and the digit grouping*; the
`i18n-prefs` cookie sets only which currency is displayed; the delivery
country decides the offer itself — which seller, which price, and whether a
price is shown at all. Left alone, amazon.de quotes an export price in SAR to
a Saudi IP while the domain says EUR.

So by default the tracker pins the delivery country to the storefront's own
country. The reason is time-series stability rather than price accuracy: a
tracking bot compares today against yesterday, and if the price follows the
server's location, moving the server or rotating a proxy produces a phantom
jump and a false discount alert.

```python
from productspy.trackers.amazon import AmazonTracker

# default: market pinned to the domain's country
AmazonTracker("https://www.amazon.de/dp/B09WVVZQD3").fetch()

# don't pin — take whatever Amazon serves this IP
AmazonTracker(url, pin_market=False).fetch()

# override the market: "lang", "lang:CUR" or "lang:CUR:COUNTRY"
AmazonTracker(url, locale="en-GB:GBP:GB").fetch()
```

Pinning costs one extra request per storefront per `Fetcher`, and the state
is kept in the session, so every later product on that storefront reuses it.
If it fails, the fetch still succeeds — you get the export-market price
instead of the local one rather than an error.

Two Amazon-specific keys land in `raw`: `location_blocked`, set when the page
hides the price because it will not ship to the pinned country (which is
*not* the same as out of stock), and `availability_text`, the stock wording in
the storefront's own language.

## Contribute

Feel free to open an issue or pull request.