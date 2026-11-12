"""Synthetic canaries for the complete detection/review/external-call boundary."""
import copy
import io
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.notes.generate import app
from api.notes.recompose import app as recompose_app
from app.api.security import require_preview_access
from app.core.config import settings
from app.schemas.note import SessionInput
from app.services import deid_review as review
from app.services import qwen_deidentification as qwen
from app.services.embeddings import EmbeddingError, OpenAIEmbeddingProvider
from app.services.llm import get_llm

RAW = "😀 이름은 윤가온입니다. 연락처는 010-0000-3141입니다. 약 5mg을 2주 복용하지 않았고 검사점수는 72점이다."


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"deid_review_signing_key": "synthetic-review-secret-" * 3,
                            "require_deid_review": True, "enable_real_user_auth": False,
                            "runtime_environment": "test", "remind_allow_local_bypass": True,
                            "remind_preview_actor": "synthetic-owner"}.items():
            self.stack.enter_context(patch.object(settings, name, value))
        self.stack.enter_context(patch("app.services.deid_review.detect_entities", return_value=qwen.Entities(entities=[
            qwen.Entity(original="윤가온", category="name"), qwen.Entity(original="010-0000-3141", category="contact"),
        ])))
        self.client = TestClient(app)

    def reviewed(self):
        initial = review.ReviewStart(purpose="quick", payload={"text": RAW})
        found = review.start_review(initial, "synthetic-owner")
        edits = [review.SpanEdit(path="/text", start=RAW.index(value), end=RAW.index(value)+len(value),
                                original=value, replacement=label)
                 for value, label in [("윤가온", "[내담자 A]"), ("010-0000-3141", "[연락처 비공개]")]]
        confirmed = review.confirm_review(review.ReviewConfirm(purpose="quick", payload=found["payload"],
                                            detection_token=found["detection_token"], edits=edits), "synthetic-owner")
        return found, confirmed

    def test_detect_confirm_and_only_reviewed_text_enters_generation(self):
        _, approved = self.reviewed()
        text = approved["payload"]["text"]
        self.assertNotIn("윤가온", text)
        self.assertNotIn("010-0000-3141", text)
        self.assertIn("약 5mg을 2주 복용하지 않았고 검사점수는 72점", text)
        # A provider error proves the route got past the receipt boundary, without a real call.
        with patch("app.api.routes.notes.generate_quick_summary", side_effect=RuntimeError()) as generate:
            response = self.client.post("/api/notes/quick-summary", json=approved["payload"],
                                        headers={"X-Review-Receipt": approved["receipt"]})
            self.assertEqual(502, response.status_code)
            self.assertEqual(text, generate.call_args.args[0])

    def test_missing_tampered_changed_actor_expired_and_wrong_purpose_are_rejected(self):
        _, approved = self.reviewed()
        changed = {"text": RAW}
        for token, payload in [("", approved["payload"]), (approved["receipt"] + "x", approved["payload"]),
                               (approved["receipt"], changed)]:
            with self.subTest(token=bool(token)), patch("app.api.routes.notes.generate_quick_summary") as generate:
                response = self.client.post("/api/notes/quick-summary", json=payload, headers={"X-Review-Receipt": token})
                self.assertEqual(409, response.status_code)
                generate.assert_not_called()
        for actor, purpose in [("other-owner", "quick"), ("synthetic-owner", "generate")]:
            with self.assertRaises(HTTPException):
                review._verify(approved["receipt"], "reviewed", purpose, approved["payload"], actor)
        with patch("app.services.deid_review.time.time", return_value=10**12), self.assertRaises(HTTPException):
            review._verify(approved["receipt"], "reviewed", "quick", approved["payload"], "synthetic-owner")

    def test_detected_token_cannot_authorize_generation_and_changed_source_cannot_confirm(self):
        found, approved = self.reviewed()
        with self.assertRaises(HTTPException):
            review._verify(found["detection_token"], "reviewed", "quick", found["payload"], "synthetic-owner")
        with self.assertRaises(HTTPException):
            review.confirm_review(review.ReviewConfirm(purpose="quick", payload={"text": RAW + "changed"},
                                  detection_token=found["detection_token"]), "synthetic-owner")
        self.assertNotIn("윤가온", found["detection_token"] + approved["receipt"])

    def test_detector_failure_has_no_receipt_or_regex_only_success(self):
        with patch("app.services.deid_review.detect_entities", side_effect=qwen.DetectionUnavailable("private-detail")):
            response = self.client.post("/api/notes/deidentification-preview", json={"purpose": "quick", "payload": {"text": RAW}})
        self.assertEqual(503, response.status_code)
        self.assertNotIn("detection_token", response.text)
        self.assertNotIn("private-detail", response.text)

    def test_pending_job_is_bound_to_its_actor_source_and_purpose(self):
        pending = qwen.PendingDetection(job_id="synthetic-job")
        with patch("app.services.deid_review.detect_entities", return_value=pending):
            response = review.start_review(review.ReviewStart(purpose="quick", payload={"text": RAW}), "synthetic-owner")
        self.assertEqual("pending", response["status"])
        self.assertNotIn("items", response)
        for actor, text in [("other-owner", RAW), ("synthetic-owner", RAW + " changed")]:
            with patch("app.services.deid_review.detect_entities") as detect, self.assertRaises(HTTPException):
                review.start_review(review.ReviewStart(purpose="quick", payload={"text": text}, job_token=response["job_token"]), actor)
            detect.assert_not_called()
        with patch("app.services.deid_review.detect_entities", return_value=qwen.Entities(entities=[])) as detect:
            completed = review.start_review(review.ReviewStart(purpose="quick", payload={"text": RAW}, job_token=response["job_token"]), "synthetic-owner")
        self.assertTrue(completed["model_used"])
        self.assertEqual("synthetic-job", detect.call_args.kwargs["job_id"])

    def test_worker_rejects_unauthenticated_body_before_parsing(self):
        from app.deid_worker import app as worker_app
        with patch.dict("os.environ", {"DEID_SERVICE_TOKEN": "synthetic-worker-secret"}), patch("app.deid_worker.detect_on_ollama") as model:
            for path in ["/detect", "/jobs"]:
                response = TestClient(worker_app).post(path, content="invalid JSON")
                self.assertEqual(401, response.status_code)
            model.assert_not_called()

    def test_recomposition_api_cannot_bypass_review(self):
        recompose_app.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"
        self.addCleanup(recompose_app.dependency_overrides.clear)
        data = {"session_input": {"case_id": "synthetic", "session_number": 1, "counselor_memo": RAW, "transcript_text": ""}}
        with patch("app.api.routes.notes.recompose_note_with_cache") as generate:
            response = TestClient(recompose_app).post("/api/notes/recompose", json=data)
        self.assertEqual(409, response.status_code)
        generate.assert_not_called()

    def test_all_supplementary_source_text_is_reviewed_and_metadata_is_not_in_prompt(self):
        payload = SessionInput(case_id="RAW_CASE_CANARY", client_alias="RAW_ALIAS_CANARY", counselor_name="RAW_COUNSELOR_CANARY",
            session_number=1, counselor_memo="memo", transcript_text="text", counseling_goal="GOAL_CANARY", key_issue_tags=["TAG_CANARY"])
        material = [item["text"] for item in review.sources(payload.model_dump())]
        self.assertIn("GOAL_CANARY", material)
        self.assertIn("TAG_CANARY", material)
        result = json.dumps(review.prompt_material(payload))
        for value in ["RAW_CASE_CANARY", "RAW_ALIAS_CANARY", "RAW_COUNSELOR_CANARY"]:
            self.assertNotIn(value, result)

    def test_embeddings_and_llm_fail_without_review_and_context_does_not_leak(self):
        with patch("app.services.embeddings.urlopen") as send:
            with self.assertRaises(EmbeddingError):
                OpenAIEmbeddingProvider("synthetic", "synthetic").embed([RAW])
            send.assert_not_called()
        with patch("app.services.llm.ChatOpenAI") as llm, self.assertRaises(HTTPException):
            get_llm()
        llm.assert_not_called()
        _, approved = self.reviewed()
        with review.reviewed_request("quick", review.QuickSummaryRequest(**approved["payload"]), approved["receipt"], "synthetic-owner"):
            self.assertTrue(review.embedding_is_reviewed(approved["payload"]["text"]))
            self.assertFalse(review.embedding_is_reviewed(RAW))
        self.assertFalse(review.embedding_is_reviewed(approved["payload"]["text"]))


class QwenTests(unittest.TestCase):
    def reply(self, content, **kwargs):
        return io.BytesIO(json.dumps({"done": True, "done_reason": "stop", "message": {"content": content}, **kwargs}).encode())

    def test_exact_entity_schema_and_tail_coverage(self):
        text = "가" * 2798 + "경계이름" + "나" * 3200 + "꼬리이름"
        seen = []
        def respond(request, **_):
            body = json.loads(request.data)
            chunk = body["messages"][-1]["content"]
            seen.append(chunk)
            self.assertEqual("http://127.0.0.1:11434/api/chat", request.full_url)
            entities = [{"original": name, "category": "name"} for name in ["경계이름", "꼬리이름"] if name in chunk]
            return self.reply(json.dumps({"entities": entities}))
        with patch.object(qwen, "urlopen", side_effect=respond):
            result = qwen.detect_on_ollama([text])
        self.assertEqual({"경계이름", "꼬리이름"}, {item.original for item in result.entities})
        self.assertTrue(seen[-1].endswith("꼬리이름"))

    def test_incomplete_malformed_hallucinated_or_unavailable_detection_never_succeeds(self):
        for reply in [self.reply('{"entities": []}', done_reason="length"), self.reply("bad JSON"),
                      self.reply('{"entities":[{"original":"not-in-source","category":"name"}]}')]:
            with patch.object(qwen, "urlopen", return_value=reply), self.assertRaises(qwen.DetectionUnavailable):
                qwen.detect_on_ollama([RAW])
        with patch.object(qwen, "urlopen", side_effect=TimeoutError()), self.assertRaises(qwen.DetectionUnavailable):
            qwen.detect_on_ollama([RAW])


if __name__ == "__main__":
    unittest.main()
