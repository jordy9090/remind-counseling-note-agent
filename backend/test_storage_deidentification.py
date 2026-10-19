"""Names and occupations are de-identified before counseling data is stored. Synthetic data only.

The model call is replaced by a fixed extraction, so these tests check the masking rules and every
storage entry point, not the provider's recall.
Run: python -m unittest test_storage_deidentification
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import storage_deidentification as deid
from test_persistence_workflow import INPUT, TOKEN, offline_environment

MEMO = "김민지 내담자는 초등학교 교사로 일한다. 민지가 동생 박서준과 다툰 뒤 싱어송라이터인 친구에게 연락했다."
ENTITIES = deid._StorageEntities(
    person_names=["김민지", "민지", "박서준", "없는사람"],
    occupations=[
        deid._OccupationMention(text="초등학교 교사", category="교육자"),
        deid._OccupationMention(text="싱어송라이터", category="예술가"),
    ],
)


def model_returns(entities):
    return patch.object(deid, "_extract_entities", return_value=entities)


class MaskingRuleTests(unittest.TestCase):
    def test_name_masks_middle_characters(self) -> None:
        self.assertEqual(deid.mask_name("홍길동"), "홍O동")
        self.assertEqual(deid.mask_name("홍길동삼"), "홍OO삼")
        self.assertEqual(deid.mask_name("민지"), "민O")
        self.assertEqual(deid.mask_name("남궁민수"), "남OO수")
        self.assertEqual(deid.mask_name("김"), "김")

    def test_occupation_field_becomes_a_broad_category(self) -> None:
        cases = {"초등학교 교사": "교육자", "교수": "교육자", "연예인": "예술가", "싱어송라이터": "예술가",
                 "직장인": "사무직 종사자", "간호사": "의료인", "한의사": "의료인", "대학생": "학생",
                 "소방관": "공공 부문 종사자", "개발자": "IT·기술직 종사자", "우주비행사": "기타 직업군",
                 "교육자": "교육자"}
        for value, category in cases.items():
            with self.subTest(value=value):
                self.assertEqual(deid.occupation_category(value), category)
        self.assertIsNone(deid.occupation_category("  "))
        self.assertTrue(set(deid.OCCUPATION_CATEGORIES) >= set(cases.values()))

    def test_model_mentions_are_masked_and_generalized_in_text(self) -> None:
        with model_returns(ENTITIES):
            texts, report = deid.deidentify_texts({"memo": MEMO})
        self.assertEqual(texts["memo"], "김O지 내담자는 교육자로 일한다. 민O가 동생 [PERSON]과 다툰 뒤 예술가인 친구에게 연락했다.")
        self.assertTrue(report.llm_used)
        self.assertEqual((report.names_masked, report.occupations_generalized), (2, 2))

    def test_names_are_not_masked_inside_other_words_or_twice(self) -> None:
        entities = deid._StorageEntities(person_names=["지원", "홍O동"], occupations=[])
        with model_returns(entities):
            texts, _ = deid.deidentify_texts({"memo": "지원이가 상담을 지원했다. 학교지원 프로그램. 홍O동"})
        self.assertEqual(texts["memo"], "지O이가 상담을 지O했다. 학교지원 프로그램. 홍O동")

    def test_without_the_model_the_client_alias_is_still_masked(self) -> None:
        with model_returns(None):
            texts, report = deid.deidentify_texts({"memo": MEMO}, known_names=["김민지", "합성 가명"])
        self.assertIn("김O지 내담자", texts["memo"])
        self.assertIn("민O가", texts["memo"])
        self.assertIn("교육자", texts["memo"])
        self.assertFalse(report.llm_used)

    def test_disabled_extraction_does_not_repeat_known_name_scan(self) -> None:
        known_names = ["김민지", "박상담"]
        texts = {"memo": "김민지와 박상담이 만났다.", "note": "민지와 상담 이야기"}
        expected_scans = len(deid._alias_names(known_names)) * len(texts)

        with model_returns(None), patch.object(deid, "_name_pattern", wraps=deid._name_pattern) as name_pattern:
            result, report = deid.deidentify_texts(texts, known_names=known_names)

        self.assertEqual(result, {"memo": "김O지와 박O담이 만났다.", "note": "민O와 상담 이야기"})
        self.assertEqual(report.names_masked, 3)
        self.assertFalse(report.llm_used)
        self.assertEqual(name_pattern.call_count, expected_scans)

    def test_opt_in_extraction_scans_only_new_names_on_the_second_pass(self) -> None:
        known_names = ["김민지"]
        texts = {"memo": "김민지와 최하늘은 도예가로 일한다.", "note": "민지와 최하늘 이야기"}
        entities = deid._StorageEntities(
            person_names=["김민지", "최하늘"],
            occupations=[deid._OccupationMention(text="도예가", category="예술가")],
        )
        expected_scans = (len(deid._alias_names(known_names)) + 1) * len(texts)

        with model_returns(entities), patch.object(deid, "_name_pattern", wraps=deid._name_pattern) as name_pattern:
            result, report = deid.deidentify_texts(texts, known_names=known_names)

        self.assertEqual(result, {
            "memo": "김O지와 최O늘은 예술가로 일한다.",
            "note": "민O와 최O늘 이야기",
        })
        self.assertEqual((report.names_masked, report.occupations_generalized), (4, 1))
        self.assertTrue(report.llm_used)
        self.assertEqual(name_pattern.call_count, expected_scans)
        self.assertEqual(
            [call.args[0] for call in name_pattern.call_args_list].count("최하늘"),
            len(texts),
        )

    def test_opt_in_extraction_deduplicates_candidates_before_membership_checks(self) -> None:
        entities = deid._StorageEntities(
            person_names=["최하늘", "하늘"] * 100,
            occupations=[
                deid._OccupationMention(text="아동도예가", category="예술가"),
                deid._OccupationMention(text="도예가", category="예술가"),
            ] * 100,
        )
        text = "최하늘은 하늘과 아동도예가 및 도예가로 일한다."

        with model_returns(entities), patch.object(
            deid, "_candidate_is_present", wraps=deid._candidate_is_present,
        ) as candidate_is_present:
            result, report = deid.deidentify_texts({"memo": text})

        self.assertEqual(result["memo"], "최O늘은 하O과 예술가 및 예술가로 일한다.")
        self.assertEqual((report.names_masked, report.occupations_generalized), (2, 2))
        self.assertEqual(candidate_is_present.call_count, 4)
        self.assertEqual(
            {call.args[0] for call in candidate_is_present.call_args_list},
            {"최하늘", "하늘", "아동도예가", "도예가"},
        )

    def test_default_fallback_masks_contextual_third_party_name_and_common_occupation(self) -> None:
        with patch.object(settings, "allow_external_storage_entity_extraction", False):
            texts, report = deid.deidentify_texts({"memo": "친구 박서준은 간호사로 일한다."})
        self.assertEqual("친구 [PERSON]은 의료인으로 일한다.", texts["memo"])
        self.assertFalse(report.llm_used)

    def test_stub_mode_never_calls_the_provider(self) -> None:
        with patch.object(settings, "allow_external_storage_entity_extraction", True), patch.object(settings, "use_stub", True), patch("app.services.llm.get_structured_llm",
                                                            side_effect=AssertionError("provider called")):
            self.assertIsNone(deid._extract_entities(MEMO))

    def test_external_entity_extraction_is_disabled_by_default(self) -> None:
        with patch.object(settings, "allow_external_storage_entity_extraction", False), patch.object(
            settings, "use_stub", False
        ), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.services.llm.get_structured_llm", side_effect=AssertionError("provider called")
        ):
            texts, report = deid.deidentify_texts(
                {"memo": "이름: 김민지, 010-1234-5678, minji@example.com, 한빛고등학교"},
                known_names=["김민지"],
            )
        self.assertFalse(report.llm_used)
        for raw in ("김민지", "010-1234-5678", "minji@example.com", "한빛고등학교"):
            self.assertNotIn(raw, texts["memo"])

    def test_opt_in_extraction_receives_only_deterministically_masked_text(self) -> None:
        captured: list[str] = []
        runnable = Mock()
        runnable.invoke.side_effect = lambda prompt: captured.append(prompt) or deid._StorageEntities()
        with patch.object(settings, "allow_external_storage_entity_extraction", True), patch.object(
            settings, "use_stub", False
        ), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.services.llm.get_structured_llm", return_value=runnable
        ):
            deid.deidentify_texts(
                {"memo": "최하늘 010-1234-5678 minji@example.com 한빛고등학교 싱어송라이터"},
                known_names=["최하늘"],
            )
        self.assertEqual(1, runnable.invoke.call_count)
        provider_text = captured[0].split("Text:\n", 1)[1]
        for raw in ("최하늘", "010-1234-5678", "minji@example.com", "한빛고등학교", "싱어송라이터"):
            self.assertNotIn(raw, provider_text)
        self.assertIn("최O늘", provider_text)

    def test_provider_errors_fall_back_quietly(self) -> None:
        with patch.object(settings, "allow_external_storage_entity_extraction", True), patch.object(settings, "use_stub", False), patch.object(settings, "openai_api_key", "synthetic-key"), \
                patch("app.services.llm.get_structured_llm", side_effect=RuntimeError("synthetic outage")):
            self.assertIsNone(deid._extract_entities(MEMO))

    def test_json_payloads_keep_identifiers_and_enums(self) -> None:
        payload = {"draft_id": "draft_김민지", "case_id": "case_1", "screen": "session_input",
                   "form": {"counselor_memo": MEMO, "key_issue_tags": ["민지 갈등"]},
                   "sections": [{"id": "s1", "title": "상담 내용", "content": "민지는 교사가 꿈이었다."}]}
        with model_returns(ENTITIES):
            result, _ = deid.deidentify_json(payload)
        self.assertEqual(result["draft_id"], "draft_김민지")
        self.assertEqual(result["screen"], "session_input")
        self.assertEqual(result["form"]["key_issue_tags"], ["민O 갈등"])
        self.assertIn("교육자로", result["form"]["counselor_memo"])
        self.assertEqual(result["sections"][0]["content"], "민O는 교사가 꿈이었다.")

    def test_json_payloads_preserve_only_curated_theory_source_urls(self) -> None:
        payload = {
            "result": {
                "relational_insights": {
                    "theory_sources": [{"url": "https://example.org/synthetic"}],
                },
            },
            "content": "내담자 계정은 https://example.org/minji 이다.",
        }

        result, _ = deid.deidentify_json(payload)

        self.assertEqual(
            "https://example.org/synthetic",
            result["result"]["relational_insights"]["theory_sources"][0]["url"],
        )
        self.assertNotIn("https://example.org/minji", result["content"])
        self.assertIn("[ACCOUNT]", result["content"])


class StorageEntryPointTests(unittest.TestCase):
    """Every save path stores the de-identified text, through the real routes and storage code."""

    def setUp(self) -> None:
        self.context = offline_environment()
        self.store = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}
        model = model_returns(ENTITIES)
        model.start()
        self.addCleanup(model.stop)

    def stored_text(self, table: str) -> str:
        return json.dumps(self.store.tables.get(table, []), ensure_ascii=False)

    def assert_deidentified(self, text: str) -> None:
        for raw in ("김민지", "민지가", "박서준", "초등학교 교사", "싱어송라이터"):
            self.assertNotIn(raw, text)

    def test_generation_deidentifies_derived_storage_and_preserves_configured_original(self) -> None:
        response = self.client.post("/api/notes/generate", headers=self.headers,
                                    json={**INPUT, "client_alias": "김민지", "counselor_memo": MEMO})
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertTrue(response.json()["persistence_report"]["stored"])
        for table in ("generated_notes", "cases"):
            with self.subTest(table=table):
                self.assert_deidentified(self.stored_text(table))
        session = self.store.tables["sessions"][0]
        self.assertEqual(MEMO, json.loads(session["raw_input_text"])["counselor_memo"])
        self.assert_deidentified(session["sanitized_input_text"])
        self.assertIn("교육자로 일한다", session["sanitized_input_text"])
        self.assertEqual(self.store.tables["cases"][0]["case_alias"], "김O지")

    def test_client_profile_is_stored_with_masked_name_and_category(self) -> None:
        created = self.client.post("/api/cases", headers=self.headers, json={
            "case_alias": "홍길동", "client_age": 30, "client_occupation": "연예인", "client_notes": MEMO})
        self.assertEqual(created.status_code, 201, created.text[:300])
        row = self.store.tables["cases"][0]
        self.assertEqual((row["case_alias"], row["client_occupation"]), ("홍O동", "예술가"))
        self.assert_deidentified(row["client_notes"])
        updated = self.client.patch(f'/api/cases/{created.json()["case_id"]}/profile', headers=self.headers,
                                    json={"case_alias": "홍길동삼", "client_occupation": "교수"})
        self.assertEqual(updated.status_code, 200, updated.text[:300])
        self.assertEqual((updated.json()["case_alias"], updated.json()["client_occupation"]), ("홍OO삼", "교육자"))

    def test_temporary_drafts_and_confirmations_are_stored_deidentified(self) -> None:
        saved = self.client.post("/api/notes/drafts", headers=self.headers, json={
            "case_id": INPUT["case_id"], "session_number": 1, "form": {**INPUT, "counselor_memo": MEMO},
            "draft_sections": [{"id": "session_content", "title": "상담 내용", "content": MEMO, "visible": True}]})
        self.assertEqual(saved.status_code, 200, saved.text[:300])
        self.assert_deidentified(self.stored_text(settings.supabase_drafts_table))

        generated = self.client.post("/api/notes/generate", headers=self.headers, json=INPUT).json()
        confirm = self.client.post("/api/notes/confirm", headers=self.headers, json={
            "note_id": generated["persistence_report"]["note_id"], "counselor_edited": True,
            "confirmed_note": {"session_content": {"text": MEMO}, "sections": {"session_content": MEMO}}})
        self.assertEqual(confirm.status_code, 200, confirm.text[:300])
        self.assert_deidentified(self.stored_text("generated_notes"))


if __name__ == "__main__":
    unittest.main()
