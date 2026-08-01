class ProductSpyError(Exception):
    """Base class — catch this to catch anything from productspy."""


class UnsupportedSiteError(ProductSpyError):
    """No tracker is registered for this domain."""


class FetchError(ProductSpyError):
    """The page could not be retrieved (network, timeout, 4xx/5xx)."""


class BlockedError(FetchError):
    """The site actively refused us: 403/429/503, CAPTCHA, or bot wall.

    Distinct from FetchError on purpose — this is the signal to rotate a
    proxy or back off, not to mark the product as broken.
    """


class ParseError(ProductSpyError):
    """The page loaded but the expected fields were not found.

    Usually means the site changed its markup and the tracker needs a fix.
    """