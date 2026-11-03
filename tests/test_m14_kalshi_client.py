"""Synthetic Ed25519 keys and fake responses only; no account requests."""
import base64
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import unittest
from urllib.error import HTTPError, URLError

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from m14_kalshi_client import KalshiReadOnly, NoRedirect, ReadOnlyError


def pem(key=None):
    key = key or ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


class Response:
    status = 200
    def __init__(self, data=None, *, prohibit_read=False):
        self.raw = json.dumps({} if data is None else data).encode()
        self.prohibit_read = prohibit_read
        self.reads = 0
    def __enter__(self):return self
    def __exit__(self, *args):return None
    def read(self, size):
        self.reads += 1
        if self.prohibit_read:raise AssertionError("Authentication must not read balances")
        return self.raw[:size]


class ClientTests(unittest.TestCase):
    def test_signature_verifies_exact_method_path_timestamp_without_query(self):
        key, requests = ed25519.Ed25519PrivateKey.generate(), []
        def opener(request, timeout):
            requests.append(request)
            self.assertEqual(timeout, 20)
            return Response({"fills": [], "cursor": ""})
        client = KalshiReadOnly("synthetic-key", pem(key), opener=opener, clock_ms=lambda: 1700000000123)
        client.get_json("/portfolio/fills", {"subaccount": 0, "limit": 100, "cursor": "synthetic-cursor"})
        request = requests[0]
        signature = base64.b64decode(request.get_header("Kalshi-access-signature"))
        key.public_key().verify(signature, b"1700000000123GET/trade-api/v2/portfolio/fills")
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.startswith("https://external-api.kalshi.com/trade-api/v2/"))
        self.assertIsNone(request.data)
        self.assertNotIn("synthetic-key", request.full_url)

    def test_authentication_never_reads_or_stores_balance_body(self):
        response = Response({"balance": "SENSITIVE_BALANCE"}, prohibit_read=True)
        client = KalshiReadOnly("synthetic-key", pem(), opener=lambda *a, **k: response)
        self.assertIsNone(client.authenticate())
        self.assertEqual(response.reads, 0)
        with self.assertRaises(ReadOnlyError):client.get_json("/portfolio/balance")

    def test_only_declared_read_routes_are_possible(self):
        requests = []
        client = KalshiReadOnly("synthetic-key", pem(), opener=lambda *a, **k: requests.append(a))
        for route in ("/portfolio/orders", "/portfolio/transfers", "https://evil.invalid/portfolio/fills", "/portfolio/positions/../orders"):
            with self.subTest(route=route), self.assertRaises(ReadOnlyError):client.get_json(route)
        self.assertEqual(requests, [])

    def test_scope_and_pagination_parameters_are_validated_before_network(self):
        requests = []
        client = KalshiReadOnly("synthetic-key", pem(), opener=lambda *a, **k: requests.append(a))
        for query in ({"subaccount": True}, {"subaccount": 64}, {"limit": 0}, {"method": "POST"},
                      {"min_ts": 1}, {"ticker": "FILTERED"}, {"cursor": None}, {"settlement_status": "unsettled"}):
            with self.subTest(query=query), self.assertRaises(ReadOnlyError):client.get_json("/portfolio/positions", query)
        self.assertEqual(requests, [])

    def test_non_ed25519_and_invalid_credentials_are_rejected(self):
        rsa_pem = pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
        for key_id, private in (("", pem()), ("key\ninjection", pem()), ("synthetic-key", rsa_pem),
                                ("synthetic-key", "SENSITIVE_INVALID_KEY"), ("synthetic-key", "")):
            with self.subTest(key_id=key_id), self.assertRaises(ReadOnlyError) as raised:
                KalshiReadOnly(key_id, private)
            self.assertNotIn("SENSITIVE", str(raised.exception))
            self.assertNotIn("PRIVATE KEY", str(raised.exception))

    def test_http_failures_never_expose_key_or_response_body(self):
        output, errors = StringIO(), StringIO()
        for status, category in ((401, "http_401"), (403, "http_403"), (429, "http_429"), (503, "http_5xx"), (302, "redirect_refused")):
            def fail(*args, **kwargs):
                raise HTTPError("https://example.invalid/SENSITIVE", status, "SENSITIVE", {}, BytesIO(b"SENSITIVE_BALANCE"))
            client = KalshiReadOnly("synthetic-key", pem(), opener=fail)
            with redirect_stdout(output), redirect_stderr(errors), self.subTest(status=status), self.assertRaises(ReadOnlyError) as raised:
                client.authenticate()
            self.assertEqual(str(raised.exception), category)
        self.assertEqual(output.getvalue() + errors.getvalue(), "")

    def test_redirect_handler_cannot_forward_authentication_headers(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid"))

    def test_malformed_duplicate_or_nonfinite_json_is_rejected(self):
        for raw in (b'{"fills":[],"fills":[]}', b'{"value":NaN}', b'SENSITIVE_INVALID_JSON', b'[]'):
            response = Response()
            response.raw = raw
            client = KalshiReadOnly("synthetic-key", pem(), opener=lambda *a, **k: response)
            with self.subTest(raw=raw), self.assertRaises(ReadOnlyError) as raised:
                client.get_json("/historical/cutoff")
            self.assertEqual(str(raised.exception), "response_schema")

    def test_network_errors_are_redacted(self):
        def fail(*args, **kwargs):raise URLError("SENSITIVE_ENDPOINT")
        client = KalshiReadOnly("synthetic-key", pem(), opener=fail)
        with self.assertRaises(ReadOnlyError) as raised:client.authenticate()
        self.assertEqual(str(raised.exception), "network_unavailable")
