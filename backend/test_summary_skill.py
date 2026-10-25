"""Offline contracts for the opt-in single-call session-summary skill."""
from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.schemas.note import SensitiveInfoCandidate, SessionSummaryDraft
from app.services import summary_skill
from app.services.summary_quality import SummaryQualityError
from test_summary_quality import _state, _summary


SKILL_DOCUMENT = """---
name: session-summary
description: Summarize one de-identified counseling session.
---
입력 자료에 근거해 한국어 회기요약 초안을 작성하세요.
"""


class SummarySkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sanitized = _state()["sanitized_input"]
        self.fields = _summary().model_dump(exclude={"session_info"})
        self.path = Mock()
        self.path.read_text.return_value = SKILL_DOCUMENT
        self.provider = Mock()
        self.structured = self.provider.with_structured_output.return_value
        self.structured.invoke.return_value = {
            "parsed": self.fields,
            "parsing_error": None,
            "raw": SimpleNamespace(usage_metadata=None, response_metadata={}),
        }
        for patcher in (
            patch.object(settings, "openai_api_key", "synthetic-not-a-provider-key"),
            patch.object(settings, "use_stub", False),
            patch.object(summary_skill, "SKILL_PATH", self.path),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        provider_patcher = patch.object(summary_skill, "get_llm", return_value=self.provider)
        self.get_llm = provider_patcher.start()
        self.addCleanup(provider_patcher.stop)

    def test_request_sends_sources_once_and_excludes_private_metadata(self) -> None:
        self.sanitized.case_id = "SYNTH-PRIVATE-CASE-MARKER"
        self.sanitized.client_alias = "SYNTH-PRIVATE-CLIENT-MARKER"
        self.sanitized.counselor_name = "SYNTH-PRIVATE-COUNSELOR-MARKER"
        self.sanitized.sensitive_info_candidates = [SensitiveInfoCandidate(
            text="SYNTH-PRIVATE-CANDIDATE-MARKER", source="transcript_text",
            category="person", recommendation="검토 필요",
        )]
        self.sanitized.sources.transcript_text = "내담자: SYNTH-TRANSCRIPT-ONCE\n상담자: 어떤 마음인가요?"
        request = summary_skill.build_summary_skill_request(self.sanitized)
        body = json.loads(request.messages[1].content)
        self.assertEqual(self.sanitized.sources.transcript_text, body["sources"]["transcript_text"])
        self.assertEqual(self.sanitized.sources.counselor_memo, body["sources"]["counselor_memo"])
        serialized = "\n".join(message.content for message in request.messages)
        self.assertEqual(1, serialized.count("SYNTH-TRANSCRIPT-ONCE"))
        self.assertNotIn("SYNTH-PRIVATE", serialized)
        self.assertNotIn("previous_session_summary", body["sources"])
        self.assertEqual(
            ["counselor_memo", "transcript_text", "transcript.turn_1", "transcript.turn_2"],
            body["allowed_source_refs"],
        )
        self.get_llm.assert_not_called()

    def test_skill_content_changes_request_and_fingerprint_without_provider_calls(self) -> None:
        initial = summary_skill.build_summary_skill_request(self.sanitized)
        self.path.read_text.return_value = SKILL_DOCUMENT + "\n화자를 정확히 구분하세요.\n"
        changed = summary_skill.build_summary_skill_request(self.sanitized)
        self.assertNotEqual(initial.skill_sha256, changed.skill_sha256)
        self.assertIn("화자를 정확히 구분하세요.", changed.messages[0].content)
        self.assertEqual(initial.messages[1].content, changed.messages[1].content)
        self.get_llm.assert_not_called()

    def test_prior_session_input_is_rejected_without_silent_discard(self) -> None:
        self.sanitized.sources.previous_session_summary = "이전 회기에서 관계의 어려움을 이야기함."
        with self.assertRaises(summary_skill.SummarySkillError):
            summary_skill.run_summary_skill(self.sanitized)
        self.path.read_text.assert_not_called()
        self.get_llm.assert_not_called()

    def test_empty_current_session_input_is_rejected_before_provider_setup(self) -> None:
        self.sanitized.sources.transcript_text = " \n"
        self.sanitized.sources.counselor_memo = " "
        with self.assertRaises(summary_skill.SummarySkillError):
            summary_skill.run_summary_skill(self.sanitized)
        self.get_llm.assert_not_called()

    def test_missing_key_and_explicit_stub_fail_closed(self) -> None:
        for key, stub in ((None, False), ("", False), ("synthetic-key", True)):
            with self.subTest(stub=stub, has_key=bool(key)), patch.object(
                settings, "openai_api_key", key,
            ), patch.object(settings, "use_stub", stub):
                with self.assertRaises(summary_skill.SummarySkillError):
                    summary_skill.run_summary_skill(self.sanitized)
        self.path.read_text.assert_not_called()
        self.get_llm.assert_not_called()

    def test_one_structured_call_returns_compatible_sections_and_local_metadata(self) -> None:
        self.sanitized.case_id = "SYNTH-LOCAL-METADATA"
        self.sanitized.session_number = 7
        result = summary_skill.run_summary_skill(self.sanitized)
        self.get_llm.assert_called_once_with(max_retries=0)
        self.provider.with_structured_output.assert_called_once_with(
            summary_skill.SummarySkillFields, include_raw=True,
        )
        self.structured.invoke.assert_called_once()
        self.assertIsInstance(result.summary, SessionSummaryDraft)
        self.assertEqual("SYNTH-LOCAL-METADATA", result.summary.session_info.case_id)
        self.assertEqual(7, result.summary.session_info.session_number)
        self.assertEqual(7, len(result.summary.model_dump(exclude={"session_info"})))
        self.assertEqual(self.fields["session_content"]["text"], result.summary.session_content.text)
        self.assertEqual(["transcript_text"], result.summary.session_content.source_refs)
        self.assertEqual(1, result.model_calls)
        self.assertEqual("draft_requires_counselor_confirmation", result.status)
        self.assertIn("semantic_verification_not_run", result.verification)
        self.assertIsNone(result.usage)
        self.assertIsNone(result.response_model)

    def test_unknown_reference_is_removed_and_marked_for_review(self) -> None:
        self.fields["session_content"]["source_refs"] = ["transcript.turn_9000", "invented-source"]
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertEqual([], result.summary.session_content.source_refs)
        self.assertTrue(result.summary.session_content.requires_review)
        self.structured.invoke.assert_called_once()

    def test_valid_reference_preserves_order_without_inventing_semantic_verification(self) -> None:
        self.fields["session_content"]["source_refs"] = ["counselor_memo", "transcript_text", "counselor_memo"]
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertEqual(["counselor_memo", "transcript_text"], result.summary.session_content.source_refs)
        self.assertIn("semantic_verification_not_run", result.verification)

    def test_undocumented_counselor_reflection_is_replaced(self) -> None:
        self.fields["reflection"] = {
            "text": "상담자는 스스로 내담자를 빨리 안심시키려 했다고 성찰함.",
            "evidence_type": "direct", "source_refs": ["transcript_text"], "requires_review": False,
        }
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertEqual("[상담사 확인 필요]", result.summary.reflection.text)
        self.assertEqual("counselor_input", result.summary.reflection.evidence_type)
        self.assertEqual([], result.summary.reflection.source_refs)
        self.assertTrue(result.summary.reflection.requires_review)

    def test_documented_counselor_reflection_remains_reviewable(self) -> None:
        self.sanitized.sources.counselor_memo = "답답하지 않다고 바로 안심시켜주고 싶은 마음이 들었음."
        self.fields["reflection"] = {
            "text": "상담자는 바로 안심시켜주고 싶은 마음이 들었다고 기록함.",
            "evidence_type": "counselor_input", "source_refs": ["counselor_memo"], "requires_review": False,
        }
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertEqual(self.fields["reflection"]["text"], result.summary.reflection.text)
        self.assertEqual(["counselor_memo"], result.summary.reflection.source_refs)
        self.assertTrue(result.summary.reflection.requires_review)

    def test_provider_cannot_override_session_metadata(self) -> None:
        self.fields["session_info"] = {"case_id": "SYNTH-UNTRUSTED-OVERRIDE", "session_number": 99}
        with self.assertRaises(summary_skill.SummarySkillError) as caught:
            summary_skill.run_summary_skill(self.sanitized)
        self.assertNotIn("SYNTH-UNTRUSTED-OVERRIDE", str(caught.exception))
        self.structured.invoke.assert_called_once()

    def test_missing_or_unparseable_output_fails_without_second_call(self) -> None:
        for result in (
            {"parsed": None, "parsing_error": None},
            {"parsed": self.fields, "parsing_error": ValueError("SYNTH-PARSE-DETAIL")},
            {"parsed": {"session_content": self.fields["session_content"]}, "parsing_error": None},
        ):
            with self.subTest(keys=list(result)):
                self.structured.invoke.reset_mock()
                self.structured.invoke.return_value = result
                with self.assertRaises(summary_skill.SummarySkillError) as caught:
                    summary_skill.run_summary_skill(self.sanitized)
                self.assertNotIn("SYNTH-PARSE-DETAIL", str(caught.exception))
                self.assertNotIn(self.fields["session_content"]["text"], str(caught.exception))
                self.structured.invoke.assert_called_once()

    def test_provider_failure_does_not_leak_error_or_retry(self) -> None:
        self.structured.invoke.side_effect = RuntimeError("SYNTH-PROVIDER-PRIVATE-DETAIL")
        with self.assertRaises(summary_skill.SummarySkillError) as caught:
            summary_skill.run_summary_skill(self.sanitized)
        self.assertNotIn("SYNTH-PROVIDER-PRIVATE-DETAIL", str(caught.exception))
        self.structured.invoke.assert_called_once()

    def test_quality_failure_has_no_automatic_repair_or_mock_fallback(self) -> None:
        self.fields["session_content"]["text"] = "계속 확인해요. 잠이 안 와요. 걱정돼요."
        with self.assertRaises(SummaryQualityError) as caught:
            summary_skill.run_summary_skill(self.sanitized)
        self.assertNotIn(self.fields["session_content"]["text"], str(caught.exception))
        self.structured.invoke.assert_called_once()

    def test_only_numeric_provider_usage_and_model_identity_are_retained(self) -> None:
        self.structured.invoke.return_value["raw"] = SimpleNamespace(
            usage_metadata={
                "input_tokens": 321, "output_tokens": 45, "total_tokens": 366,
                "provider_private_field": "SYNTH-PRIVATE-USAGE-DETAIL",
            },
            response_metadata={"model_name": "synthetic-model-version", "headers": {"secret": "synthetic"}},
            content="SYNTH-PRIVATE-RAW-CONTENT",
        )
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertEqual({"input_tokens": 321, "output_tokens": 45, "total_tokens": 366}, result.usage)
        self.assertEqual("synthetic-model-version", result.response_model)
        self.assertNotIn("SYNTH-PRIVATE", repr(result))
        self.assertFalse(hasattr(result, "raw"))

    def test_invalid_usage_is_unavailable_instead_of_reported_as_zero(self) -> None:
        self.structured.invoke.return_value["raw"] = SimpleNamespace(
            usage_metadata={"input_tokens": True, "output_tokens": -1, "total_tokens": "unknown"},
            response_metadata={"model_name": 123},
        )
        result = summary_skill.run_summary_skill(self.sanitized)
        self.assertIsNone(result.usage)
        self.assertIsNone(result.response_model)


if __name__ == "__main__":
    unittest.main()
