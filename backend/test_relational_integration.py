"""Synthetic API/persistence checks for review-only relational insights."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.insight import RelationalInsights
from test_persistence_workflow import INPUT, TOKEN, OTHER_TOKEN, offline_environment


def insights_fixture() -> RelationalInsights:
    return RelationalInsights.model_validate({
        "status": "generated", "lens": "psychodynamic_relational",
        "cards": [{
            "id": "synthetic-card", "focus": "intervention_response",
            "observation": "내담자는 산책한 뒤 편안함을 보고함.",
            "hypothesis": "산책 경험의 의미를 더 탐색할 가능성이 있음.",
            "alternative_explanation": "산책 외의 다른 상황 변화가 영향을 주었을 수 있음.",
            "counterevidence_or_missing": "다른 상황에서의 정서 변화는 제공되지 않았음.",
            "supervision_questions": ["내담자가 경험한 변화를 더 확인할 필요가 있는가?"],
            "evidence": [{"source_ref": "transcript_text", "quote": INPUT["transcript_text"]}],
            "theory_source_ids": ["synthetic-supervision"], "requires_review": True,
        }],
        "theory_sources": [{
            "id": "synthetic-supervision", "title": "Synthetic source for a local test",
            "organization": "Synthetic", "url": "https://example.org/synthetic",
            "locator": "Test-only", "principle": "Reflect on the client's account.",
            "concepts": ["intervention_response"], "limitations": "Synthetic test source.",
        }], "notices": [],
    })


class RelationalIntegrationTests(unittest.TestCase):
    def setUp(self):
        context = offline_environment()
        self.store = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def test_automatic_generation_persists_and_reopens_separate_from_confirmed_facts(self):
        with patch("app.graph.graph.generate_relational_insights", return_value=insights_fixture()) as generate:
            response = self.client.post("/api/notes/generate", headers=self.headers,
                                        json=INPUT)
        self.assertEqual(200, response.status_code)
        generate.assert_called_once()
        result = response.json()
        self.assertEqual("generated", result["relational_insights"]["status"])
        self.assertNotIn("relational_insights", result["session_summary_draft"])
        self.assertNotIn("relational_insights", result["confirmed_session_note"])
        note_id = result["persistence_report"]["note_id"]
        url = f"/api/notes/records/{note_id}"
        loaded = self.client.get(url, headers=self.headers).json()
        self.assertEqual(result["relational_insights"], loaded["draft_json"]["relational_insights"])
        self.assertEqual("psychodynamic_relational", loaded["draft_json"]["insight_lens"])
        confirmed = {"sections": {"session_content": "상담사가 검토한 합성 요약"},
                     "relational_insights": result["relational_insights"]}
        response = self.client.post("/api/notes/confirm", headers=self.headers, json={
            "note_id": note_id, "confirmed_note": confirmed, "counselor_edited": True, "create_case_memory": False,
        })
        self.assertEqual(200, response.status_code)
        reopened = self.client.get(url, headers=self.headers).json()
        self.assertNotIn("relational_insights", reopened["confirmed_json"])
        self.assertEqual(result["relational_insights"], reopened["draft_json"]["relational_insights"])
        self.assertEqual(404, self.client.get(url, headers={"Authorization": f"Bearer {OTHER_TOKEN}"}).status_code)

    def test_explicit_api_opt_out_skips_additional_generation(self):
        with patch("app.graph.graph.generate_relational_insights") as generate:
            response = self.client.post("/api/notes/generate", headers=self.headers,
                                        json={**INPUT, "insight_lens": "none"})
        self.assertEqual(200, response.status_code)
        generate.assert_not_called()
        self.assertIsNone(response.json()["relational_insights"])

    def test_explicit_demo_never_presents_model_insights(self):
        response = self.client.post("/api/notes/generate", headers=self.headers,
                                    json={**INPUT, "insight_lens": "psychodynamic_relational"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("demo", response.json()["relational_insights"]["status"])
        self.assertEqual([], response.json()["relational_insights"]["cards"])

    def test_temporary_draft_keeps_insights_and_drops_unknown_model_metadata(self):
        insights = insights_fixture().model_dump(mode="json")
        insights["hidden_prompt"] = "DROP-ME"
        payload = {"case_id": INPUT["case_id"], "session_number": 1,
                   "form": {**INPUT, "insight_lens": "psychodynamic_relational"},
                   "result": {"relational_insights": insights}}
        response = self.client.post("/api/notes/drafts", headers=self.headers, json=payload)
        self.assertEqual(200, response.status_code)
        saved = self.client.get(f'/api/notes/drafts/{response.json()["draft_id"]}', headers=self.headers).json()
        self.assertEqual(insights_fixture().model_dump(mode="json"), saved["result"]["relational_insights"])
        self.assertEqual("psychodynamic_relational", saved["form"]["insight_lens"])


if __name__ == "__main__":
    unittest.main()
