"""Tests for case dashboard aggregation, alias mapping, and transcript status.

Runs offline (no Supabase, no network):
  uv run python test_case_dashboard.py
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.note import CaseScheduleUpdateRequest, SessionInput
from app.services.supabase_storage import (
    _note_summary_text,
    _resolve_case_alias,
    _transcript_status,
)


def make_input(**overrides) -> SessionInput:
    payload = {
        "case_id": "CASE-001",
        "session_number": 3,
        "counselor_memo": "메모",
        "transcript_text": "상담사: 안녕하세요.",
    }
    payload.update(overrides)
    return SessionInput(**payload)


class CaseAliasTests(unittest.TestCase):
    def test_client_alias_is_stored_as_case_alias(self) -> None:
        session_input = make_input(client_alias="가명 은하")
        self.assertEqual(_resolve_case_alias(session_input, None), "가명 은하")

    def test_existing_alias_is_preserved_when_input_is_empty(self) -> None:
        """재생성 시 alias가 case_id로 되돌아가는 회귀를 방지한다."""
        session_input = make_input(client_alias="")
        existing = {"case_alias": "가명 은하"}
        self.assertEqual(_resolve_case_alias(session_input, existing), "가명 은하")

    def test_case_id_is_fallback_when_no_alias_exists(self) -> None:
        session_input = make_input(client_alias="  ")
        self.assertEqual(_resolve_case_alias(session_input, {}), "CASE-001")
        self.assertEqual(_resolve_case_alias(session_input, None), "CASE-001")


class TranscriptStatusTests(unittest.TestCase):
    def test_completed_when_transcript_present(self) -> None:
        self.assertEqual(_transcript_status(make_input()), "completed")

    def test_none_when_transcript_missing(self) -> None:
        self.assertEqual(_transcript_status(make_input(transcript_text="  ")), "none")


class NoteSummaryTests(unittest.TestCase):
    def test_confirmed_json_wins_over_draft(self) -> None:
        note_row = {
            "draft_json": {"session_theme": {"text": "초안 주제"}},
            "confirmed_json": {"session_theme": {"text": "확정 주제"}},
        }
        self.assertEqual(_note_summary_text(note_row), "확정 주제")

    def test_falls_back_to_draft_and_secondary_fields(self) -> None:
        note_row = {
            "draft_json": {"session_content": {"text": "회기 내용 요약"}},
            "confirmed_json": {},
        }
        self.assertEqual(_note_summary_text(note_row), "회기 내용 요약")

    def test_returns_none_when_no_summary(self) -> None:
        self.assertIsNone(_note_summary_text({"draft_json": {}, "confirmed_json": {}}))


class ScheduleValidationTests(unittest.TestCase):
    def test_negative_session_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CaseScheduleUpdateRequest(total_scheduled_session_count=-1)

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CaseScheduleUpdateRequest(next_scheduled_date="2026/01/01")

    def test_valid_payload_passes(self) -> None:
        request = CaseScheduleUpdateRequest(
            total_scheduled_session_count=10, next_scheduled_date="2026-03-27"
        )
        self.assertEqual(request.total_scheduled_session_count, 10)
        self.assertEqual(request.next_scheduled_date, "2026-03-27")

    def test_empty_date_normalizes_to_none(self) -> None:
        self.assertIsNone(CaseScheduleUpdateRequest(next_scheduled_date="").next_scheduled_date)


class DashboardRouteTests(unittest.TestCase):
    """Supabase 미구성 환경에서 라우트가 안전하게 응답하는지 확인한다.

    인증 의존성은 override해 라우트 자체의 동작(검증·가드)을 검증한다.
    인증 미구성 환경에서는 require_preview_access가 먼저 503을 반환한다는 것도
    별도 테스트로 고정한다.
    """

    def setUp(self) -> None:
        from app.api.security import require_preview_access

        app.dependency_overrides[require_preview_access] = lambda: "test-actor"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_unauthenticated_request_is_rejected_by_security_layer(self) -> None:
        app.dependency_overrides.clear()
        response = TestClient(app).get("/api/cases/CASE-001/dashboard")
        self.assertIn(response.status_code, (401, 403, 503))

    def test_dashboard_returns_503_without_supabase(self) -> None:
        with patch("app.api.routes.cases.settings") as mock_settings:
            mock_settings.supabase_configured = False
            response = self.client.get("/api/cases/CASE-001/dashboard")
        self.assertEqual(response.status_code, 503)

    def test_schedule_returns_503_without_supabase(self) -> None:
        with patch("app.api.routes.cases.settings") as mock_settings:
            mock_settings.supabase_configured = False
            response = self.client.patch(
                "/api/cases/CASE-001/schedule",
                json={"total_scheduled_session_count": 5},
            )
        self.assertEqual(response.status_code, 503)

    def test_schedule_rejects_negative_count(self) -> None:
        response = self.client.patch(
            "/api/cases/CASE-001/schedule",
            json={"total_scheduled_session_count": -3},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
