import re
from urllib.parse import urlparse
import requests
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

def resolve_short_url(url: str) -> str:
    try:
        response = requests.get(url, allow_redirects=True, timeout=10)
        return response.url
    except requests.RequestException:
        return url
