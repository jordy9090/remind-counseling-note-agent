"""Unit tests for the metadata-only local model probe."""
from __future__ import annotations

import unittest
from pathlib import Path

from benchmarks.local_transformers_probe import extract_json_object, model_identity, score_summary


class LocalTransformersProbeTests(unittest.TestCase):
    def test_extracts_first_complete_json_object(self) -> None:
        parsed = extract_json_object(
            'prefix {"main_content":"괄호 { 유지", "next_plan":"없음"} suffix'
        )
        self.assertEqual("괄호 { 유지", parsed["main_content"])

    def test_invalid_output_fails_without_echoing_content(self) -> None:
        self.assertIsNone(extract_json_object("not-json"))
        self.assertFalse(score_summary(None)["json_object"])

    def test_scores_the_synthetic_evidence_contract(self) -> None:
        checks = score_summary({
            "main_content": "발표 준비와 잠들기 어려운 경험을 다룸.",
            "counselor_intervention": "걱정 상황과 신체 반응을 탐색함.",
            "client_response": "걱정을 표현함.",
            "next_plan": "새로운 계획은 합의하지 않음.",
        })
        self.assertTrue(all(checks.values()))

    def test_model_identity_uses_hugging_face_cache_name_and_revision(self) -> None:
        label, revision = model_identity(Path(
            "/cache/models--Qwen--Qwen2.5-7B-Instruct/snapshots/synthetic-revision"
        ))
        self.assertEqual("Qwen/Qwen2.5-7B-Instruct", label)
        self.assertEqual("synthetic-revision", revision)


if __name__ == "__main__":
    unittest.main()
