"""ExtraTracker: JSON-LD path plus the (unverified) dataLayer fallback."""

from bs4 import BeautifulSoup

from productspy.registry import resolve_tracker
from productspy.trackers.extra import ExtraTracker


class _FakeResponse:
    status_code = 200
    url = "http://shop.test/p"
    text = "<html><body><h1>x</h1></body></html>"


class _FakeFetcher:
    def get(self, url, **kwargs):
        return _FakeResponse()


JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Laptop",
 "offers":{"@type":"Offer","price":"2499","priceCurrency":"SAR",
           "availability":"https://schema.org/InStock"}}
</script>
</head><body></body></html>
"""


def test_extra_parses_json_ld():
    soup = BeautifulSoup(JSON_LD_PAGE, "html.parser")
    tracker = ExtraTracker("https://www.extra.com/p", fetcher=_FakeFetcher())
    data = tracker.parse(soup, JSON_LD_PAGE)
    assert data["name"] == "Laptop"
    assert data["price"] == "2499"
    assert data["currency"] == "SAR"


DATA_LAYER_PAGE = """
<html><head>
<script>
dataLayer.push({"event":"view_item","ecommerce":{"items":[
  {"item_name":"Blender","price":"349","currency":"SAR"}
]}});
</script>
</head><body></body></html>
"""


def test_extra_falls_back_to_data_layer():
    soup = BeautifulSoup(DATA_LAYER_PAGE, "html.parser")
    tracker = ExtraTracker("https://www.extra.com/p", fetcher=_FakeFetcher())
    data = tracker.parse(soup, DATA_LAYER_PAGE)
    assert data["name"] == "Blender"
    assert data["price"] == "349"
    assert data["currency"] == "SAR"


def test_resolve_tracker_extra():
    assert resolve_tracker("extra.com") is ExtraTracker