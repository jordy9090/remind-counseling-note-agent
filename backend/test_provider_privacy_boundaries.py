"""Provider-bound counseling material is deterministically de-identified first."""
from __future__ import annotations

import unittest

from app.graph.nodes import _build_structure_prompt, _build_summary_prompt, sanitize_input
from app.schemas.note import EvidenceMappedData, SessionInput, StructuredCaseData
from app.services.deidentification import mask_known_names, render_counselor_text
from app.services.retrieval import retrieval_query_from_input


class ProviderPrivacyBoundaryTests(unittest.TestCase):
    def test_generation_and_embedding_inputs_exclude_known_identifiers(self) -> None:
        raw_values = (
            "김민지",
            "박상담",
            "010-1234-5678",
            "minji@example.com",
            "한빛고등학교",
            "간호사",
        )
        sanitized = sanitize_input({
            "session_input": SessionInput(
                case_id="PRIVATE-CASE-ID",
                client_alias="김민지",
                counselor_name="박상담",
                session_number=1,
                counselor_memo="민지: 박상담： 010-1234-5678과 minji@example.com을 전달했다.",
                transcript_text="내담자: 한빛고등학교 간호사 이야기를 했다.",
                key_issue_tags=["민지 연락처 010-1234-5678"],
            )
        })["sanitized_input"]

        prompt = _build_structure_prompt(sanitized, [], None)
        query = retrieval_query_from_input("session_note", sanitized.sources)
        for raw in raw_values:
            self.assertNotIn(raw, prompt)
            self.assertNotIn(raw, query)
        self.assertNotIn("PRIVATE-CASE-ID", prompt)

        self.assertEqual("김민지", sanitized.client_alias)
        self.assertEqual("박상담", sanitized.counselor_name)
        self.assertIn("[CLIENT]", sanitized.sources.counselor_memo)
        self.assertIn("[COUNSELOR]", sanitized.sources.counselor_memo)
        self.assertIn("[PHONE]", query)

    def test_contextual_masking_preserves_role_nouns_and_name_prefixes(self) -> None:
        sanitized = sanitize_input({
            "session_input": SessionInput(
                case_id="synthetic-case",
                client_alias="김민지",
                counselor_name="상담자",
                session_number=1,
                counselor_memo="친구 이야기는 중요하고 김민지원은 다른 사람이다.",
                transcript_text="상담자가 친구 박서준은 왔다고 말했다.",
            )
        })["sanitized_input"]
        self.assertIn("친구 이야기는", sanitized.sources.counselor_memo)
        self.assertIn("김민지원", sanitized.sources.counselor_memo)
        self.assertIn("상담자가", sanitized.sources.transcript_text)
        self.assertIn("친구 [PERSON]은", sanitized.sources.transcript_text)

    def test_known_name_masking_accepts_common_speaker_label_delimiters(self) -> None:
        replacements = {"김민지": "[CLIENT]"}

        for text in (
            "김민지: 발화",
            "김민지： 발화",
            "[김민지] 발화",
            "김민지) 발화",
            "김민지-발화",
        ):
            with self.subTest(text=text):
                self.assertNotIn("김민지", mask_known_names(text, replacements))

        self.assertEqual(
            "김민지원은 다른 사람이다.",
            mask_known_names("김민지원은 다른 사람이다.", replacements),
        )

    def test_recompose_topic_masks_known_names_and_keeps_roles_distinct(self) -> None:
        sanitized = sanitize_input({
            "session_input": SessionInput(
                case_id="synthetic-case",
                client_alias="김민지",
                counselor_name="박상담",
                session_number=1,
                counselor_memo="박상담이 김민지에게 질문했다.",
                transcript_text="",
            )
        })["sanitized_input"]
        prompt = _build_summary_prompt(
            sanitized,
            StructuredCaseData(),
            EvidenceMappedData(),
            session_topic="[김민지] 박상담-관계",
        )
        self.assertNotIn("김민지", prompt)
        self.assertNotIn("박상담", prompt)

        masked = mask_known_names(
            "박상담이 김민지에게 질문했다.",
            {"김민지": "[CLIENT]", "박상담": "[COUNSELOR]"},
        )
        self.assertEqual("상담자가 김민지에게 질문했다.", render_counselor_text(masked, client_alias="김민지"))
