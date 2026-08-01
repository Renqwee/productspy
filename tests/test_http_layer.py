"""HTTP layer tests against a real local server.

`responses` patches `requests`, which curl_cffi never touches — those mocks
were silently bypassed and the tests passed on DNS failure instead.
A throwaway localhost server exercises the real code path.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from productspy import BlockedError, FetchError
from productspy.http import FetchConfig, Fetcher


class _Handler(BaseHTTPRequestHandler):
    """Serves whatever status code the path asks for: /status/403"""

    def do_GET(self):
        try:
            code = int(self.path.rsplit("/", 1)[-1])
        except ValueError:
            code = 200
        body = b"<html><body>ok</body></html>"
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep pytest output clean


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def fetcher():
    """No delays — otherwise retries add ~6s per test."""
    return Fetcher(FetchConfig(min_delay=0, jitter=0, backoff_factor=0))


@pytest.mark.parametrize("code", [403, 429, 503])
def test_block_codes_raise_blocked(server, fetcher, code):
    with pytest.raises(BlockedError):
        fetcher.get(f"{server}/status/{code}")


@pytest.mark.parametrize("code", [500, 502, 504])
def test_retry_codes_raise_fetch_error_not_blocked(server, fetcher, code):
    with pytest.raises(FetchError) as exc:
        fetcher.get(f"{server}/status/{code}")
    assert not isinstance(exc.value, BlockedError)


@pytest.mark.parametrize("code", [400, 404, 410])
def test_client_errors_raise_fetch_error_not_blocked(server, fetcher, code):
    with pytest.raises(FetchError) as exc:
        fetcher.get(f"{server}/status/{code}")
    assert not isinstance(exc.value, BlockedError)


def test_success_returns_response(server, fetcher):
    response = fetcher.get(f"{server}/status/200")
    assert response.status_code == 200
    assert "ok" in response.text


def test_404_is_not_retried(server, fetcher):
    """A missing page won't appear on the second try — one attempt only."""
    attempts = {"n": 0}
    original = fetcher._session.get

    def counting_get(*args, **kwargs):
        attempts["n"] += 1
        return original(*args, **kwargs)

    fetcher._session.get = counting_get
    with pytest.raises(FetchError):
        fetcher.get(f"{server}/status/404")
    assert attempts["n"] == 1


def test_block_code_is_retried(server, fetcher):
    """403 gets the full retry budget: 1 original + max_retries."""
    attempts = {"n": 0}
    original = fetcher._session.get

    def counting_get(*args, **kwargs):
        attempts["n"] += 1
        return original(*args, **kwargs)

    fetcher._session.get = counting_get
    with pytest.raises(BlockedError):
        fetcher.get(f"{server}/status/403")
    assert attempts["n"] == fetcher.config.max_retries + 1


def test_custom_headers_override_defaults(server, fetcher):
    seen = {}
    original = fetcher._session.get

    def capturing_get(*args, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return original(*args, **kwargs)

    fetcher._session.get = capturing_get
    fetcher.get(f"{server}/status/200", headers={"Referer": "https://x.test"})
    assert seen["Referer"] == "https://x.test"
    assert "Sec-Fetch-Mode" in seen  # defaults survive the merge