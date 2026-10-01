"""Synthetic regressions for complete session materials pasted into the memo."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from app.graph.nodes import _source_catalog, sanitize_input
from app.schemas.note import SessionInput
from app.services.session_materials import separate_session_materials


TRANSCRIPT = "A01 상담자: 어떤 마음이 남았나요?\n\nA02 내담자: 아쉬운 마음이 남았어요."
REFLECTION = "바로 안심시켜주고 싶은 마음이 들었음."


def _input(memo: str, transcript: str = "") -> SessionInput:
    return SessionInput(
        case_id="SYNTH-MEMO-MATERIALS", session_number=1, session_date="2026-10-02",
        counselor_memo=memo, transcript_text=transcript,
    )


def _combined(transcript: str = TRANSCRIPT, prefix: str = "### ") -> str:
    return (
        f"{prefix}A-0. 사례 소개\n\n이전 회기 원문은 제공하지 않음.\n\n"
        f"{prefix}A-1. 합성 축어록\n\n{transcript}\n\n"
        f"{prefix}A-2. 상담 직후 메모\n\n- {REFLECTION}\n"
    )


class SessionMaterialsTests(unittest.TestCase):
    def test_explicit_sections_separate_without_changing_original_input(self):
        for prefix in ("### ", ""):
            with self.subTest(markdown=bool(prefix)):
                original = _input(_combined(prefix=prefix))
                before = original.model_dump()
                sanitized = sanitize_input({"session_input": original})["sanitized_input"]
                self.assertEqual(before, original.model_dump())
                self.assertEqual(TRANSCRIPT, sanitized.sources.transcript_text)
                self.assertIn(REFLECTION, sanitized.sources.counselor_memo)
                self.assertIn("이전 회기 원문은 제공하지 않음.", sanitized.sources.counselor_memo)
                self.assertNotIn("A01", sanitized.sources.counselor_memo)
                self.assertNotIn("합성 축어록", sanitized.sources.counselor_memo)

    def test_supplied_case_preserves_all_turns_reflections_and_source_spans(self):
        fixture = Path(__file__).parent / "evaluation_cases" / "relational_memo_a.txt"
        original = _input(fixture.read_text(encoding="utf-8"))
        before = original.model_dump()
        sanitized = sanitize_input({"session_input": original})["sanitized_input"]
        sources = sanitized.sources
        expected_turns = re.findall(r"^A\d{2} .+$", original.counselor_memo, re.MULTILINE)
        actual_turns = re.findall(r"^A\d{2} .+$", sources.transcript_text, re.MULTILINE)
        self.assertEqual(32, len(actual_turns))
        self.assertEqual(expected_turns, actual_turns)
        self.assertEqual(before, original.model_dump())
        self.assertNotRegex(sources.counselor_memo, r"(?m)^A\d{2} ")
        self.assertIn("안심시켜주고 싶은 마음이 들었고", sources.counselor_memo)
        self.assertIn("침묵에 대해 해명하고 싶은 마음도 들었음", sources.counselor_memo)
        self.assertIn("이전 회기 원문·심리검사·가족력은 제공하지 않음", sources.counselor_memo)
        self.assertIn("별도의 행동 과제는 정하지 않음", sources.counselor_memo)
        self.assertNotIn("상담 직후 메모", sources.transcript_text)
        catalog = _source_catalog(sanitized, [])
        turn_sources = [value for ref, value in catalog.items() if ref.startswith("transcript.turn_")]
        self.assertEqual(expected_turns, turn_sources)
        self.assertIn("사실은 왜 아무 말씀도 안 하시지, 조금 서운했어요.", catalog["transcript_text"])

    def test_prose_and_unlabelled_or_unheaded_material_are_unchanged(self):
        memos = [
            "  내담자가 서운했다고 말함. 나는 안심시키고 싶은 마음이 들었음.\n",
            "축어록을 보고 다음 회기에 질문하기로 함.\n상담자: 어떤 마음인가요?",
            TRANSCRIPT,
            "### 합성 축어록\n\n누가 말했는지 표시되지 않은 문장.\n\n### 상담 직후 메모\n" + REFLECTION,
        ]
        for memo in memos:
            with self.subTest(memo_length=len(memo)):
                result = separate_session_materials(memo, "")
                self.assertEqual(memo, result.counselor_memo)
                self.assertEqual("", result.transcript_text)

    def test_separate_transcript_is_preserved_and_duplicate_not_added(self):
        existing = "  " + TRANSCRIPT.replace("\n\n", "\n") + "\n"
        result = separate_session_materials(_combined(), existing)
        self.assertEqual(existing, result.transcript_text)
        self.assertNotIn("A01", result.counselor_memo)
        self.assertIn(REFLECTION, result.counselor_memo)

    def test_distinct_separate_transcript_is_retained_before_extracted_block(self):
        existing = "B01 내담자: 오늘은 괜찮았어요.\nB02 상담자: 어떤 일이 있었나요?\n"
        result = separate_session_materials(_combined(), existing)
        self.assertEqual(existing + "\n\n" + TRANSCRIPT, result.transcript_text)
        self.assertEqual(1, result.transcript_text.count("A01"))
        self.assertIn(REFLECTION, result.counselor_memo)

    def test_unknown_markdown_heading_ends_transcript_section(self):
        memo = "## 축어록\n" + TRANSCRIPT + "\n\n## 추가 맥락\n확인하지 못한 자료가 있음."
        result = separate_session_materials(memo, "")
        self.assertEqual(TRANSCRIPT, result.transcript_text)
        self.assertEqual("## 추가 맥락\n확인하지 못한 자료가 있음.", result.counselor_memo)

    def test_numbered_speaker_lines_do_not_end_explicit_transcript_sections(self):
        for marker in (".", ")", ""):
            with self.subTest(marker=marker):
                transcript = (
                    f"1{marker} 상담자: 어떤 마음인가요?\n\n"
                    f"2{marker} 내담자: 서운했어요."
                )
                memo = "### 축어록\n" + transcript + "\n\n2. 상담 직후 메모\n" + REFLECTION
                original = _input(memo)
                sanitized = sanitize_input({"session_input": original})["sanitized_input"]
                self.assertEqual(transcript, sanitized.sources.transcript_text)
                self.assertEqual("2. 상담 직후 메모\n" + REFLECTION, sanitized.sources.counselor_memo)
                self.assertEqual(memo, original.counselor_memo)
                self.assertEqual("", original.transcript_text)

    def test_multiple_explicit_blocks_and_crlf_quote_spans_are_preserved(self):
        first = "A01 상담자: 어떤 마음인가요?\r\n\r\nA02 내담자: 서운했어요."
        second = "B01 상담사: 더 이야기해도 괜찮아요.\r\nB02 내담자: 고마워요."
        memo = "### 축어록\r\n" + first + "\r\n\r\n### 상담자 메모\r\n" + REFLECTION
        memo += "\r\n\r\n### 상담 축어록\r\n" + second
        result = separate_session_materials(memo, "")
        self.assertEqual(first + "\n\n" + second, result.transcript_text)
        self.assertIn(REFLECTION, result.counselor_memo)
        self.assertNotIn("B01", result.counselor_memo)

    def test_derived_sources_still_pass_through_deidentification(self):
        original = _input(_combined("A01 내담자: 연락처는 synth@example.org입니다."))
        sanitized = sanitize_input({"session_input": original})["sanitized_input"]
        self.assertNotIn("synth@example.org", sanitized.sources.transcript_text)
        self.assertIn("[EMAIL]", sanitized.sources.transcript_text)
        self.assertEqual("transcript_text", sanitized.sensitive_info_candidates[0].source)
        self.assertIn("synth@example.org", original.counselor_memo)


if __name__ == "__main__":
    unittest.main()
