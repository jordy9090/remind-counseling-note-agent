"""Offline, synthetic privacy checks for both Supabase REST adapters."""
from __future__ import annotations

import io
import json
import traceback
import unittest
from http.client import HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.services import supabase_storage, supabase_store


PRIVATE_TEXT = "SYNTHETIC-PRIVATE-STORAGE-CONTENT"
PUBLIC_KEY = "synthetic-public-key"
ACCESS_TOKEN = "synthetic-user-token"


class UnreadableBody(io.BytesIO):
    def read(self, *args, **kwargs):
        raise OSError(PRIVATE_TEXT)


class ClosingFailureBody(io.BytesIO):
    def close(self):
        super().close()
        raise OSError(PRIVATE_TEXT)


class StorageDiagnosticPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        configuration = patch.multiple(
            settings, supabase_url="https://synthetic.invalid",
            supabase_publishable_key=PUBLIC_KEY, supabase_anon_key=None,
            supabase_service_key="synthetic-service-key",
        )
        configuration.start()
        self.addCleanup(configuration.stop)
        self.actor = AuthenticatedActor("synthetic-owner", ACCESS_TOKEN)

    def request(self, adapter):
        if adapter is supabase_storage:
            return adapter.SupabaseStorage(access_token=ACCESS_TOKEN)._request(
                "POST", "cases", query={"user_id": "eq.synthetic-owner"},
                body={"data": PRIVATE_TEXT}, prefer="return=representation",
            )
        return adapter._request(
            "POST", self.actor, query={"user_id": "eq.synthetic-owner"},
            body={"data": PRIVATE_TEXT}, prefer="return=representation",
        )

    def assert_private_error(self, adapter, failure, expected):
        error_type = (supabase_storage.SupabaseStorageError
                      if adapter is supabase_storage else supabase_store.DraftStorageError)
        with patch.object(adapter, "urlopen", side_effect=failure):
            try:
                self.request(adapter)
            except error_type as caught:
                message = str(caught)
                self.assertIn(expected, message)
                self.assertNotIn(PRIVATE_TEXT, message)
                self.assertNotIn(PRIVATE_TEXT, traceback.format_exc())
                self.assertIsNone(caught.__cause__)
                self.assertTrue(caught.__suppress_context__)
                return caught
            else:
                self.fail("Transport failures must remain explicit storage errors")

    def http_error(self, body, *, status=400):
        return HTTPError(
            "https://synthetic.invalid/" + PRIVATE_TEXT, status, PRIVATE_TEXT,
            {"X-Synthetic": PRIVATE_TEXT}, body,
        )

    def test_http_failure_retains_status_and_known_code_only(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                body = io.BytesIO(json.dumps({
                    "code": "23505", "message": PRIVATE_TEXT,
                    "details": PRIVATE_TEXT, "hint": PRIVATE_TEXT,
                }).encode())
                caught = self.assert_private_error(adapter, self.http_error(body, status=409), "HTTP 409")
                self.assertIn("23505", str(caught))
                self.assertTrue(body.closed)

    def test_untrusted_error_code_never_becomes_diagnostic_text(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            for code in (PRIVATE_TEXT, "LEAKS", "12345", "PGRST999", "23505\n" + PRIVATE_TEXT,
                         ["23505"], {"code": "23505"}, 23505, None):
                with self.subTest(adapter=adapter.__name__, code_type=type(code).__name__):
                    body = io.BytesIO(json.dumps({"code": code, "message": PRIVATE_TEXT}).encode())
                    caught = self.assert_private_error(adapter, self.http_error(body), "HTTP 400")
                    self.assertEqual(str(caught).split("HTTP 400", 1)[1], ".")
                    self.assertTrue(body.closed)

    def test_non_object_and_malformed_bodies_do_not_escape(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            for payload in (PRIVATE_TEXT.encode(), b"\xff", b"[]", b"null", b'"23505"', b""):
                with self.subTest(adapter=adapter.__name__, payload_type=payload[:1]):
                    body = io.BytesIO(payload)
                    self.assert_private_error(adapter, self.http_error(body), "HTTP 400")
                    self.assertTrue(body.closed)

    def test_oversized_error_body_is_not_retained(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                body = io.BytesIO(json.dumps({"code": "23505", "details": PRIVATE_TEXT * 10000}).encode())
                caught = self.assert_private_error(adapter, self.http_error(body), "HTTP 400")
                self.assertNotIn("23505", str(caught))
                self.assertTrue(body.closed)

    def test_error_body_read_failure_is_closed_and_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                body = UnreadableBody()
                self.assert_private_error(adapter, self.http_error(body), "HTTP 400")
                self.assertTrue(body.closed)

    def test_error_body_close_failure_is_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                body = ClosingFailureBody(b'{}')
                self.assert_private_error(adapter, self.http_error(body), "HTTP 400")
                self.assertTrue(body.closed)

    def test_network_reason_and_traceback_are_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                self.assert_private_error(adapter, URLError(PRIVATE_TEXT), "Supabase")

    def test_timeout_reason_and_traceback_are_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                self.assert_private_error(adapter, TimeoutError(PRIVATE_TEXT), "Supabase")

    def test_malformed_http_status_line_is_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                body = io.BytesIO((PRIVATE_TEXT + "\r\n\r\n").encode())
                socket = Mock()
                socket.makefile.return_value = body
                response = HTTPResponse(socket)
                self.addCleanup(response.close)

                def open_malformed_response(*args, **kwargs):
                    response.begin()
                    return response

                self.assert_private_error(adapter, open_malformed_response, "Supabase")

    def test_response_read_failure_is_closed_and_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                response = UnreadableBody()
                self.assert_private_error(adapter, lambda *args, **kwargs: response, "Supabase")
                self.assertTrue(response.closed)

    def test_response_decoding_failure_is_closed_and_private(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                response = io.BytesIO(PRIVATE_TEXT.encode() + b"\xff")
                self.assert_private_error(adapter, lambda *args, **kwargs: response, "Supabase")
                self.assertTrue(response.closed)

    def test_success_keeps_actor_credentials_request_and_response(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                expected = [{"id": "synthetic-row", "data": PRIVATE_TEXT}]
                response = io.BytesIO(json.dumps(expected).encode())
                with patch.object(adapter, "urlopen", return_value=response) as transport:
                    self.assertEqual(self.request(adapter), expected)
                request = transport.call_args.args[0]
                self.assertEqual(request.get_header("Apikey"), PUBLIC_KEY)
                self.assertEqual(request.get_header("Authorization"), f"Bearer {ACCESS_TOKEN}")
                self.assertEqual(request.get_header("Prefer"), "return=representation")
                self.assertEqual(json.loads(request.data), {"data": PRIVATE_TEXT})
                self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"user_id": ["eq.synthetic-owner"]})
                self.assertTrue(response.closed)

    def test_empty_success_response_remains_none(self) -> None:
        for adapter in (supabase_storage, supabase_store):
            with self.subTest(adapter=adapter.__name__):
                response = io.BytesIO()
                with patch.object(adapter, "urlopen", return_value=response):
                    self.assertIsNone(self.request(adapter))
                self.assertTrue(response.closed)

    def test_missing_column_codes_preserve_profile_fallback(self) -> None:
        client = supabase_storage.SupabaseStorage(access_token=ACCESS_TOKEN)
        for code in ("42703", "PGRST204"):
            with self.subTest(code=code), patch.object(supabase_storage, "_profile_columns_available", None):
                body = io.BytesIO(json.dumps({"code": code, "message": PRIVATE_TEXT}).encode())
                response = io.BytesIO(b'[{"id":"synthetic-case"}]')
                with patch.object(supabase_storage, "urlopen", side_effect=[self.http_error(body), response]) as transport:
                    rows = supabase_storage._select_cases(client, {"user_id": "eq.synthetic-owner"})
                self.assertEqual(rows, [{"id": "synthetic-case"}])
                self.assertEqual(transport.call_count, 2)
                self.assertFalse(supabase_storage._profile_columns_available)
                self.assertTrue(body.closed)
                fallback = transport.call_args.args[0]
                self.assertEqual(parse_qs(urlsplit(fallback.full_url).query)["select"],
                                 [supabase_storage._BASE_CASE_SELECT])
                self.assertEqual(fallback.get_header("Authorization"), f"Bearer {ACCESS_TOKEN}")

    def test_message_text_alone_cannot_trigger_profile_fallback(self) -> None:
        client = supabase_storage.SupabaseStorage(access_token=ACCESS_TOKEN)
        body = io.BytesIO(json.dumps({"code": "23505", "message": "Could not find 42703 does not exist"}).encode())
        with patch.object(supabase_storage, "_profile_columns_available", None), \
                patch.object(supabase_storage, "urlopen", side_effect=self.http_error(body)) as transport:
            with self.assertRaises(supabase_storage.SupabaseStorageError):
                supabase_storage._select_cases(client, {})
            self.assertEqual(transport.call_count, 1)
            self.assertIsNone(supabase_storage._profile_columns_available)


if __name__ == "__main__":
    unittest.main()
