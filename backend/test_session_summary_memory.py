"""Offline contracts; these do not claim to evaluate an LLM's clinical meaning."""
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph import nodes
from app.schemas.note import SessionSummaryDraft
from app.services.summary_verification import SummaryVerification
from app.services.summary_corrections import SourceRefReview
from app.services import summary_rules, summary_skill
from app.services.summary_quality import summary_quality_issues, summary_quote_issues
from test_summary_quality import _state, _summary


# Fully synthetic acceptance examples. Expected prose is authored, not generated.
# B keeps the actual wording, unlike the paraphrased quotations in the brief.
CASES = [
    ("A_body", "내담자: 목이 막히는 것 같아요.\n상담자: 그 느낌에 조금만 주의를 줘볼까요?\n내담자: 아직 답답해요.",
     "counselor_intervention", "내담자가 목이 막힌다고 말하자 상담자가 그 감각에 잠시 주의를 두도록 제안했고, 내담자는 답답함이 남아 있다고 말함.", [1, 2, 3]),
    ("B_self_criticism", "내담자: 친구에게 서운한데 제가 봐도 유치하죠.\n내담자: 저만 바보같이.\n내담자: 너는 왜 이렇게 목매냐.",
     "client_response", "내담자는 친구에게 서운한 자신을 유치하다고 평가하며 “너는 왜 이렇게 목매냐”라고 비난한다고 말함.", [1, 2, 3]),
    ("C_declined", "상담자: 잠깐 일어나서 해볼까요?\n내담자: 서서 하는 건 싫어요.\n상담자: 네. 앉아 있을게요.",
     "counselor_intervention", "상담자가 일어나서 해보자고 제안했으나 내담자가 서서 하는 것을 거절하자 상담자는 앉아 있겠다고 응답함.", [1, 2, 3]),
    ("C_no_future_plan", "상담자: 잠깐 일어나서 해볼까요?\n내담자: 서서 하는 건 싫어요.\n상담자: 네. 앉아 있을게요.",
     "next_plan", "[자료에서 확인되지 않음]", []),
    ("C_no_inferred_performance", "상담자: 잠깐 일어나서 해볼까요?\n내담자: 서서 하는 건 싫어요.\n상담자: 네. 앉아 있을게요.",
     "session_theme", "상담자가 일어나서 해보자고 제안하자 내담자가 서서 하는 것은 싫다고 거절했고, 상담자는 앉아 있겠다고 응답한 장면.", [1, 2, 3]),
    ("D_conditional_plan", "내담자: 내일 수영 끝나고 다시 읽어볼게요.\n그때도 못 보내겠으면 안 보낼 수도 있어요.",
     "next_plan", "다음 날 수영 후 다시 읽어보고 그때도 보내기 어려우면 안 보낼 수도 있다고 말함.", [1, 2]),
    ("E_scene", "내담자: 친구가 당일 약속을 취소하고 다음 약속을 먼저 잡지 않아 서운했어요.\n내담자: 연락을 피하면서도 친구가 먼저 찾아주길 기다렸어요.",
     "session_content", "친구가 당일 약속을 취소하고 다음 약속을 먼저 제안하지 않아 내담자가 서운함을 느꼈고, 연락을 피하면서도 친구가 먼저 연락하기를 기다렸다고 말함.", [1, 2]),
]


class SessionSummaryMemoryTests(unittest.TestCase):
    def test_source_line_labels_match_catalog_without_changing_saved_input(self):
        state = _state()
        source = state["sanitized_input"]
        source.sources.transcript_text = "내담자: 목이 막혀요.\r\n\r\n상담자: 잠시 주의를 두어볼까요?"
        before = source.model_dump()
        payload = summary_rules.labeled_summary_input(source)
        self.assertEqual("[transcript.turn_1] 내담자: 목이 막혀요.\n\n[transcript.turn_3] 상담자: 잠시 주의를 두어볼까요?", payload["sources"]["transcript_text"])
        self.assertEqual(before, source.model_dump())
        catalog = nodes._source_catalog(source, [])
        self.assertIn("transcript.turn_3", catalog)
        self.assertNotIn("transcript.turn_2", catalog)
        verifier = nodes._build_verification_prompt(source, state["structured_case_data"], state["evidence_mapped_data"], _summary())
        self.assertIn("[transcript.turn_3] 상담자:", verifier)

    def test_all_summary_serverless_entries_package_the_shared_skill(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
        for route in ("api/notes/generate.py", "api/notes/recompose.py"):
            self.assertEqual("backend/app/skills/**", config["functions"][route]["includeFiles"])

    def test_acceptance_examples_survive_both_generation_adapters(self):
        for name, transcript, field, text, lines in CASES:
            for route in ("quick", "regular"):
                with self.subTest(case=name, route=route), ExitStack() as stack:
                    state = _state()
                    state["sanitized_input"].sources.transcript_text = transcript
                    summary = _summary()
                    section = getattr(summary, field)
                    section.text = text
                    section.source_refs = [f"transcript.turn_{n}" for n in lines]
                    if not lines:
                        section.evidence_type = "needs_review"
                        section.requires_review = True
                    stack.enter_context(patch.multiple(settings, use_stub=False, openai_api_key="synthetic-key"))
                    if route == "quick":
                        model = Mock()
                        model.with_structured_output.return_value.invoke.return_value = {
                            "parsed": summary.model_dump(exclude={"session_info"}), "parsing_error": None,
                            "raw": SimpleNamespace(usage_metadata=None, response_metadata={}),
                        }
                        stack.enter_context(patch.object(summary_skill, "get_llm", return_value=model))
                        result = summary_skill.run_summary_skill(state["sanitized_input"]).summary
                        model.with_structured_output.return_value.invoke.assert_called_once()
                    else:
                        model = Mock(invoke=Mock(return_value=summary))
                        stack.enter_context(patch.object(nodes, "get_structured_llm", return_value=model))
                        result = nodes.generate_summary(state)["session_summary_draft"]
                        model.invoke.assert_called_once()
                    self.assertEqual(text, getattr(result, field).text)
                    self.assertEqual(section.source_refs, getattr(result, field).source_refs)
                    self.assertEqual(not bool(lines), getattr(result, field).requires_review)
                    if not lines:
                        self.assertEqual("needs_review", getattr(result, field).evidence_type)
                    self.assertEqual({}, summary_quality_issues(result))

    def test_shared_skill_edit_reaches_both_prompts_without_changing_route_scope(self):
        with TemporaryDirectory() as directory:
            skill = Path(directory) / "SKILL.md"
            document = summary_rules.SKILL_PATH.read_text(encoding="utf-8")
            skill.write_text(document + "\nSYNTHETIC-SHARED-RULE\n", encoding="utf-8")
            state = _state()
            with patch.object(summary_rules, "SKILL_PATH", skill), patch.object(summary_skill, "SKILL_PATH", skill):
                quick = summary_skill.build_summary_skill_request(state["sanitized_input"])
                regular = nodes._build_summary_prompt(state["sanitized_input"], state["structured_case_data"], state["evidence_mapped_data"])
            self.assertIn("SYNTHETIC-SHARED-RULE", quick.messages[0].content)
            self.assertIn("SYNTHETIC-SHARED-RULE", regular)
            self.assertNotIn("대사 인용, 이론 약어", regular)
            self.assertNotIn("과거 회기 검색·추정이나 별도 도구 호출은 하지 않는다", regular)

    def test_literal_quote_checks_cover_paraphrases_wrong_refs_and_missing_refs(self):
        catalog = {"transcript.turn_1": "내담자: 제가 봐도 유치하죠.",
                   "transcript.turn_2": "내담자: 아직 답답해요.",
                   "transcript_text": "내담자: 제가 봐도 유치하죠.\n내담자: 아직 답답해요."}
        for quote, refs, mismatch in [
            ("제가 봐도 유치하죠", ["transcript.turn_1"], False),
            ("유치하다", ["transcript.turn_1"], True),
            ("아직 답답해요", ["transcript.turn_1", "transcript_text"], True),
            ("아직 답답해요", ["transcript.turn_2"], False),
            ("아직 답답해요", ["transcript_text"], False),
            ("아직 답답해요", [], True),
            ("아직 답답해요", ["invented"], True),
            ("유치하죠. 내담자: 아직", ["transcript_text"], True),
        ]:
            for opening, closing in [('“', '”'), ('"', '"'), ('‘', '’'), ('「', '」')]:
                with self.subTest(quote=quote, refs=refs, opening=opening):
                    summary = _summary()
                    summary.client_response.text = f"내담자는 {opening}{quote}{closing}라고 말함."
                    summary.client_response.source_refs = refs
                    issues = summary_quote_issues(summary, catalog)
                    self.assertEqual(mismatch, "client_response" in issues)
                    self.assertNotIn(quote, str(issues))

    def test_whitespace_does_not_rewrite_words_or_morphology(self):
        summary = _summary()
        summary.client_response.text = '내담자는 “목이   막혀요”라고 말함.'
        summary.client_response.source_refs = ["transcript.turn_1"]
        self.assertEqual({}, summary_quote_issues(summary, {"transcript.turn_1": "내담자: 목이 막혀요"}))
        self.assertIn("client_response", summary_quote_issues(summary, {"transcript.turn_1": "내담자: 목이막혀요"}))

    def test_quote_mismatch_is_visible_even_when_model_verifier_accepts(self):
        state = _state()
        summary = _summary()
        summary.client_response.text = '내담자가 “이제 완전히 안정됐어요”라고 말함.'
        summary.client_response.source_refs = ["transcript.turn_3"]
        nodes._normalize_summary_refs(summary, state["sanitized_input"], [])
        self.assertTrue(summary.client_response.requires_review)
        self.assertEqual("needs_review", summary.client_response.evidence_type)
        state["session_summary_draft"] = summary
        assessment = SummaryVerification(source_ref_reviews=[
            SourceRefReview(field=field, keep_source_refs=section.source_refs)
            for field, section in summary if field != "session_info"
        ])
        with patch.multiple(settings, use_stub=False, openai_api_key="synthetic-key"), patch.object(
            nodes, "get_structured_llm", return_value=Mock(invoke=Mock(return_value=assessment)),
        ):
            report = nodes.verify_output(state)["verification_report"]
        self.assertTrue(any("직접 인용" in item.reason for item in report.unsupported_or_risky_claims))

    def test_matching_words_are_not_semantic_verification(self):
        summary = _summary()
        summary.client_response.text = '내담자는 “안정됐어요”라고 말함.'
        summary.client_response.source_refs = ["transcript.turn_1"]
        # Literal occurrence can be negated. The independent verifier is still needed.
        self.assertEqual({}, summary_quote_issues(summary, {"transcript.turn_1": '내담자: “안정됐어요”라고 말한 건 아니에요.'}))

    def test_schema_keys_and_limits_stay_compatible(self):
        summary = _summary()
        self.assertEqual(set(summary_skill.SUMMARY_FIELDS), set(SessionSummaryDraft.model_fields) - {"session_info"})
        for section in summary.model_dump(exclude={"session_info"}).values():
            self.assertEqual({"text", "evidence_type", "source_refs", "requires_review"}, set(section))
        summary.session_content.text = "긴 문장 " * 200
        self.assertIn("session_content", summary_quality_issues(summary))


if __name__ == "__main__":
    unittest.main()
