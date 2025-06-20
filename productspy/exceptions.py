class UnsupportedSiteError(Exception):
    """Raised when the provided URL is from an unsupported website."""
    pass

class FetchError(Exception):
    """Raised when the product page cannot be fetched properly."""
    pass
