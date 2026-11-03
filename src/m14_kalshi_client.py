"""Fixed-host GET-only Kalshi client. Never log requests, headers or bodies."""
import base64
import http.client
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_URL = "https://external-api.kalshi.com"
API_PREFIX = "/trade-api/v2"
ROUTES = {
    "/portfolio/balance": {"subaccount", "exchange_index"},
    "/historical/cutoff": set(),
    "/portfolio/subaccounts/netting": set(),
    "/portfolio/fills": {"subaccount", "exchange_index", "limit", "cursor"},
    "/historical/fills": {"subaccount", "limit", "cursor"},
    "/portfolio/settlements": {"subaccount", "limit", "cursor"},
    "/portfolio/positions": {"subaccount", "exchange_index", "settlement_status", "limit", "cursor"},
    "/historical/positions": {"subaccount", "limit", "cursor"},
}
CATEGORIES = frozenset(("missing_credentials", "invalid_ed25519_key", "forbidden_route", "invalid_query",
                        "http_401", "http_403", "http_429", "http_5xx", "http_other", "redirect_refused",
                        "network_unavailable", "response_schema", "response_too_large"))
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ReadOnlyError(RuntimeError):
    def __init__(self, category):
        self.category = category if category in CATEGORIES else "response_schema"
        super().__init__(self.category)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError("Nonfinite JSON")
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, TypeError):
        raise ReadOnlyError("response_schema") from None
    if not isinstance(result, dict):
        raise ReadOnlyError("response_schema")
    return result


class KalshiReadOnly:
    def __init__(self, key_id, private_pem, *, opener=None, clock_ms=None):
        if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key_id) or not private_pem:
            raise ReadOnlyError("missing_credentials")
        try:
            if not isinstance(private_pem, str) or len(private_pem) > 16384:
                raise ValueError("Invalid key format")
            key = serialization.load_pem_private_key(private_pem.strip().encode(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("Ed25519 only")
        except Exception:
            raise ReadOnlyError("invalid_ed25519_key") from None
        self._key_id, self._key = key_id, key
        self._opener = opener or build_opener(NoRedirect()).open
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._last_request = None
        http.client.HTTPConnection.debuglevel = 0

    def _request(self, route, query=None, *, discard=False):
        if route not in ROUTES:
            raise ReadOnlyError("forbidden_route")
        query = {} if query is None else query
        if not isinstance(query, dict) or set(query) - ROUTES[route]:
            raise ReadOnlyError("invalid_query")
        for key, value in query.items():
            if key in ("subaccount", "exchange_index", "limit"):
                if type(value) is not int or value < (1 if key == "limit" else 0):
                    raise ReadOnlyError("invalid_query")
                if key == "subaccount" and value > 63:
                    raise ReadOnlyError("invalid_query")
                if key == "limit" and value > 1000:
                    raise ReadOnlyError("invalid_query")
            elif key == "settlement_status" and value != "all":
                raise ReadOnlyError("invalid_query")
            elif key == "cursor" and (not isinstance(value, str) or len(value) > 8192):
                raise ReadOnlyError("invalid_query")
        if self._last_request is not None:
            remaining = 0.25 - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request = time.monotonic()
        stamp = str(self._clock_ms())
        path = API_PREFIX + route
        # Query parameters are excluded from Kalshi's signature preimage.
        signature = base64.b64encode(self._key.sign((stamp + "GET" + path).encode())).decode("ascii")
        url = BASE_URL + path + ("?" + urlencode(query) if query else "")
        request = Request(url, method="GET", headers={
            "Accept": "application/json", "User-Agent": "StatRally-M14-ReadOnly/1.0",
            "KALSHI-ACCESS-KEY": self._key_id, "KALSHI-ACCESS-TIMESTAMP": stamp,
            "KALSHI-ACCESS-SIGNATURE": signature})
        try:
            with self._opener(request, timeout=20) as response:
                if response.status != 200:
                    raise ReadOnlyError("http_other")
                if discard:
                    # Authentication-only: do not read, parse or store balances.
                    return None
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ReadOnlyError("response_too_large")
        except HTTPError as error:
            code = error.code
            error.close()
            category = ("redirect_refused" if 300 <= code < 400 else
                        f"http_{code}" if code in (401, 403, 429) else
                        "http_5xx" if 500 <= code < 600 else "http_other")
            raise ReadOnlyError(category) from None
        except (URLError, OSError, TimeoutError):
            raise ReadOnlyError("network_unavailable") from None
        return json_object(raw)

    def authenticate(self):
        self._request("/portfolio/balance", discard=True)

    def get_json(self, route, query=None):
        if route == "/portfolio/balance":
            raise ReadOnlyError("forbidden_route")
        return self._request(route, query)
