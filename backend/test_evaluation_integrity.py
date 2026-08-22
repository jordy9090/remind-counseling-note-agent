from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.evaluation.provenance import PROVENANCE_CLASSES, provenance_document
from app.graph import nodes
from app.graph.graph import run_note_pipeline
from app.graph.supervision_report import run_supervision_report_pipeline
from app.schemas.note import SessionInput, SupervisionReportRequest
from app.services import retrieval
from app.services.deidentification import deidentify_text, render_counselor_text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CANONICAL = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json"
LEGACY_TERMS = ["CASE-DEMO-001", "김민서", "이수진", "마음연결 심리상담센터", "대학 4학년", "팀 프로젝트 발표"]
INTERNAL_PLACEHOLDER_RE = re.compile(r"\[(?:PERSON|NAME|LOCATION|REDACTED|EMAIL|PHONE|ACCOUNT|RRN|STUDENT_ID|ADDRESS|INSTITUTION)\]")


def canonical_input() -> SessionInput:
    payload = json.loads(CANONICAL.read_text(encoding="utf-8"))
    payload["persist"] = False
    return SessionInput(**payload)


class EvaluationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.old = (settings.use_stub, settings.enable_rag, settings.enable_dense_retrieval, settings.enable_hybrid_retrieval)

    def tearDown(self):
        settings.use_stub, settings.enable_rag, settings.enable_dense_retrieval, settings.enable_hybrid_retrieval = self.old

    def test_no_legacy_demo_contamination(self):
        paths = [ROOT / "backend/app", ROOT / "frontend/src"]
        text = "\n".join(path.read_text(encoding="utf-8") for base in paths for path in base.rglob("*") if path.is_file() and path.suffix in {".py", ".ts", ".tsx"})
        for term in LEGACY_TERMS:
            self.assertNotIn(term, text)

    def test_muspsy_1416_is_canonical_demo(self):
        self.assertEqual(canonical_input().case_id, "CASE-MUSPSY-1416")
        fixture = (ROOT / "frontend/src/data/counselorDemoFixture.ts").read_text(encoding="utf-8")
        self.assertIn("session_input_005_muspsy_1416_ko.json", fixture)

    def test_no_internal_placeholder_in_counselor_output(self):
        ordinary_role_text, _ = deidentify_text("내담자는 예정된 시간에 참여하였다.")
        self.assertEqual(ordinary_role_text, "내담자는 예정된 시간에 참여하였다.")
        self.assertEqual(render_counselor_text("[PERSON]은 [LOCATION]에서 대기했다."), "내담자는 장소 정보 비공개에서 대기했다.")
        settings.use_stub = True
        settings.enable_rag = False
        note = run_note_pipeline(canonical_input())
        report = run_supervision_report_pipeline(
            SupervisionReportRequest(
                session_input=canonical_input(),
                session_summary_draft=note.session_summary_draft,
                demo_mode=False,
            )
        )
        counselor_output = json.dumps(
            {
                "summary": note.session_summary_draft.model_dump(mode="json"),
                "session_note": note.session_note_draft.model_dump(mode="json"),
                "termination": note.termination_report_draft.model_dump(mode="json"),
                "supervision": report.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        self.assertIsNone(INTERNAL_PLACEHOLDER_RE.search(counselor_output))

    def test_provenance_classes_valid(self):
        document = provenance_document()
        self.assertEqual(set(document["valid_source_classes"]), PROVENANCE_CLASSES)
        self.assertTrue(document["input_fields"])
        self.assertTrue(all(item["source_class"] in PROVENANCE_CLASSES for item in document["input_fields"]))

    def test_no_unattributed_supplementary_fact(self):
        by_field = {item["field"]: item for item in provenance_document()["input_fields"]}
        expected = {
            "psychological_test_summary",
            "psychological_test_summary.risk_screening",
            "counselor_memo.risk_screening",
            "counselor_memo.mse_style_observation",
            "nonverbal_notes",
        }
        self.assertTrue(expected.issubset(by_field))
        for field in expected:
            self.assertEqual(by_field[field]["source_class"], "synthetic_demo_supplement")
            self.assertTrue(by_field[field]["allowed_for_demo"])

    def test_evidence_refs_resolve(self):
        session = canonical_input()
        sanitized = nodes.sanitize_input({"session_input": session})["sanitized_input"]
        catalog = nodes._source_catalog(sanitized, [])
        refs = nodes._resolve_source_refs("생각에 대한 대차대조표를 만드는 것 같겠네요.", [], catalog)
        self.assertTrue(refs)
        self.assertTrue(all(ref in catalog for ref in refs))

    def test_evidence_source_type_matches(self):
        session = canonical_input()
        sanitized = nodes.sanitize_input({"session_input": session})["sanitized_input"]
        catalog = nodes._source_catalog(sanitized, [])
        refs = nodes._resolve_source_refs("생각에 대한 대차대조표를 만드는 것 같겠네요.", [], catalog)
        self.assertTrue(refs[0].startswith("transcript.turn_"))

    def test_verification_consistency(self):
        settings.use_stub = True
        settings.enable_rag = False
        result = run_note_pipeline(canonical_input())
        self.assertTrue(result.session_summary_draft.reflection.requires_review)
        self.assertTrue(result.verification_report.unsupported_or_risky_claims)

    def test_rag_off_has_zero_retrieval(self):
        settings.enable_rag = False
        sanitized = nodes.sanitize_input({"session_input": canonical_input()})["sanitized_input"]
        state = nodes.retrieve_context({"session_input": canonical_input(), "sanitized_input": sanitized})
        self.assertEqual(state["retrieval_report"].case_context_count, 0)
        self.assertFalse(state["retrieval_report"].enabled)

    def test_lightweight_case_context_retrieval(self):
        settings.enable_rag = True
        settings.enable_dense_retrieval = False
        sanitized = nodes.sanitize_input({"session_input": canonical_input()})["sanitized_input"]
        with patch.object(nodes, "retrieve_case_context", return_value=[]) as case, patch.object(nodes, "retrieve_document_template", return_value=None), patch.object(nodes, "retrieve_privacy_rules", return_value=[]):
            nodes.retrieve_context({"session_input": canonical_input(), "sanitized_input": sanitized})
        case.assert_called_once()

    def test_dense_case_memory_retrieval(self):
        settings.enable_rag = True
        settings.enable_dense_retrieval = True
        sanitized = nodes.sanitize_input({"session_input": canonical_input()})["sanitized_input"]
        with patch.object(nodes, "retrieve_case_memory_chunks", return_value=[]) as dense, patch.object(nodes, "retrieve_case_context", return_value=[]):
            nodes.retrieve_case_memory({"session_input": canonical_input(), "sanitized_input": sanitized, "retrieval_query": "query"})
        dense.assert_called_once()

    def test_hybrid_kb_retrieval(self):
        settings.enable_rag = settings.enable_dense_retrieval = settings.enable_hybrid_retrieval = True
        row = {"chunk_id": "1", "source_ref": "kb:test", "chunk_text": "test", "retrieval_method": "hybrid_search_kb", "metadata": {}}
        with patch.object(retrieval, "embed_query", return_value=[0.0] * 1536), patch.object(retrieval.storage, "rpc", return_value=[row]) as rpc, patch.object(retrieval, "_log_retrieval"):
            retrieval.retrieve_authoritative_kb_chunks(query_text="query", target_document_type="session_note")
        self.assertEqual(rpc.call_args.args[0], "hybrid_search_kb")

    def test_stub_rejected(self):
        settings.use_stub = True
        settings.enable_rag = False
        self.assertTrue(run_note_pipeline(canonical_input()).stub)

    def test_supervision_has_no_hardcoded_profile(self):
        settings.use_stub = True
        settings.enable_rag = False
        note = run_note_pipeline(canonical_input())
        report = run_supervision_report_pipeline(SupervisionReportRequest(session_input=canonical_input(), session_summary_draft=note.session_summary_draft, demo_mode=False))
        text = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
        for term in LEGACY_TERMS:
            self.assertNotIn(term, text)

    def test_no_invented_termination_status(self):
        settings.use_stub = True
        settings.enable_rag = False
        payload = canonical_input().model_copy(update={"target_document_type": "termination_report"})
        draft = run_note_pipeline(payload).termination_report_draft
        self.assertIsNotNone(draft)
        self.assertIn("상담사 확인", draft.sections["종결 시 상태"])
        self.assertNotIn("종결 확정", draft.sections["종결 시 상태"])

    def test_demo_package_has_no_internal_condition_labels(self):
        from package_counselor_demo import build_package

        map_path = ROOT / "eval_outputs_v4/internal/blind_condition_map.json"
        if not map_path.exists():
            self.skipTest("v4 blind artifacts are generated by the real-LLM harness")
        candidates = sorted(json.loads(map_path.read_text(encoding="utf-8")))[:2]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "counselor_demo_ready"
            build_package(candidates[0], candidates[1], output)
            for path in output.rglob("*"):
                if not path.is_file() or "internal" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8").lower()
                for term in ("7-node", "11-node", "7node", "11node", "no_rag", "lightweight", "dense", "hybrid"):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
