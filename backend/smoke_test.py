"""Smoke test for the Re:mind MVP V0 FastAPI backend.

Run from the backend directory:
    uv run python smoke_test.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.graph import nodes as graph_nodes
from app.main import app
from app.schemas.note import (
    GenerateNoteResponse,
    RetrievedCaseContextItem,
    RetrievedEvidenceItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    SessionInput,
)
from app.services.retrieval import RetrievalChunk
from app.services.supabase_storage import _build_session_row


def main() -> None:
    settings.use_stub = True
    settings.openai_api_key = None
    settings.enable_persistence = False
    settings.enable_rag = False
    settings.supabase_url = None
    settings.supabase_service_role_key = None
    settings.supabase_service_key = None
    settings.save_raw_input = False

    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json() == {"status": "ok"}

    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TEMP_DRAFT_DIR"] = temp_dir
        os.environ["RECOMPOSE_CACHE_DIR"] = str(Path(temp_dir) / "recompose")

        sample_path = Path(__file__).resolve().parents[1] / "sample_data" / "session_input_001.json"
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        response = client.post("/api/notes/generate", json=payload)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["session_summary_draft"]["session_info"]["case_id"] == payload["case_id"]
        assert data["session_summary_draft"]["session_info"]["session_number"] == payload["session_number"]
        assert data["session_summary_draft"]["session_content"]["text"]
        assert data["evidence_mapped_data"]["items"]
        assert data["verification_report"]["requires_counselor_review"]
        assert data["document_transform_preview"]["missing_required_fields"]
        assert data["confirmed_session_note"]["status"] == "draft_requires_counselor_confirmation"
        assert data["retrieval_report"]["enabled"] is False
        assert data["retrieved_case_context"] == []
        assert data["persistence_report"]["requested"] is False

        session_row = _build_session_row(SessionInput(**payload), GenerateNoteResponse(**data))
        assert session_row["raw_input_text"] is None
        assert session_row["sanitized_input_text"]
        settings.save_raw_input = True
        raw_session_row = _build_session_row(SessionInput(**payload), GenerateNoteResponse(**data))
        assert raw_session_row["raw_input_text"]
        settings.save_raw_input = False

        persist_without_supabase = client.post("/api/notes/generate", json={**payload, "persist": True})
        assert persist_without_supabase.status_code == 200, persist_without_supabase.text
        persist_data = persist_without_supabase.json()
        assert persist_data["persistence_report"]["requested"] is True
        assert persist_data["persistence_report"]["stored"] is False

        original_enable_rag = settings.enable_rag
        original_case_retrieval = graph_nodes.retrieve_case_context
        original_case_memory_chunks = graph_nodes.retrieve_case_memory_chunks
        original_authoritative_kb_chunks = graph_nodes.retrieve_authoritative_kb_chunks
        original_template_retrieval = graph_nodes.retrieve_document_template
        original_privacy_retrieval = graph_nodes.retrieve_privacy_rules
        original_enable_dense = settings.enable_dense_retrieval
        try:
            settings.enable_rag = True

            def fake_case_context(case_id: str, current_session_id: str | None = None, max_sessions: int = 3):
                return [
                    RetrievedCaseContextItem(
                        source_ref="stored_session_note:prior-session-1",
                        session_id="prior-session-1",
                        session_number=1,
                        session_date="2026-05-01",
                        summary="이전 회기에서는 진로 불안과 회피 행동을 다룸.",
                        evidence_items=[
                            RetrievedEvidenceItem(
                                id="evidence-1",
                                source_type="direct",
                                source_ref="stored_evidence:evidence-1",
                                source_text="내담자는 지원 전 회피 행동을 보고함.",
                                linked_field="session_content",
                            )
                        ],
                    )
                ]

            def fake_template_context(target_document_type):
                return RetrievedTemplateContext(
                    target_document_type=target_document_type,
                    required_fields=["주호소", "상담 내용", "다음 계획"],
                    counselor_review_fields=["사례개념화"],
                    missing_field_checklist=["사례개념화", "목표 달성 정도"],
                    source_refs=["kb_template:session-note-demo"],
                )

            def fake_privacy_rules():
                return [
                    RetrievedPrivacyRule(
                        source_ref="kb_privacy:demo-rule",
                        title="Demo privacy rule",
                        category="privacy_rule",
                        rule="Store minimum necessary counseling data.",
                        warning="저장 전 비식별화와 동의 필요 여부를 확인하세요.",
                    )
                ]

            graph_nodes.retrieve_case_context = fake_case_context
            graph_nodes.retrieve_document_template = fake_template_context
            graph_nodes.retrieve_privacy_rules = fake_privacy_rules
            rag_response = client.post("/api/notes/generate", json=payload)
            assert rag_response.status_code == 200, rag_response.text
            rag_data = rag_response.json()
            assert rag_data["retrieval_report"]["enabled"] is True
            assert rag_data["retrieval_report"]["case_context_count"] == 1
            assert rag_data["retrieval_report"]["template_context_found"] is True
            assert rag_data["retrieval_report"]["privacy_rule_count"] == 1
            assert rag_data["retrieved_case_context"][0]["source_ref"] == "stored_session_note:prior-session-1"
            assert rag_data["retrieved_template_context"]["missing_field_checklist"]
            assert rag_data["retrieved_privacy_context"][0]["warning"]

            def fake_case_memory_chunks(**kwargs):
                return [
                    RetrievalChunk(
                        chunk_id="case-memory-chunk-1",
                        session_id="prior-session-dense-1",
                        source_ref="case_memory:prior-session-dense-1:session_theme",
                        field_type="session_theme",
                        chunk_text="Dense prior-session memory matched career anxiety.",
                        retrieval_method="case_memory_dense",
                        similarity_score=0.82,
                        session_number=1,
                        session_date="2026-05-01",
                    )
                ]

            def fake_authoritative_kb_chunks(**kwargs):
                return [
                    RetrievalChunk(
                        chunk_id="kb-template-chunk-1",
                        document_id="kb-template-doc-1",
                        source_ref="kb:session-note-template-v1:1",
                        title="Session note template",
                        doc_category="session_note_template",
                        document_type="session_note",
                        allowed_use="documentation_structure_only",
                        authority_level="internal_demo",
                        chunk_text="Session notes require session content and next plan.",
                        retrieval_method="hybrid:dense+keyword",
                        similarity_score=0.7,
                        metadata={
                            "required_fields": ["session_content", "next_plan"],
                            "missing_field_checklist": ["next_plan"],
                        },
                    ),
                    RetrievalChunk(
                        chunk_id="kb-privacy-chunk-1",
                        document_id="kb-privacy-doc-1",
                        source_ref="kb:privacy-law-sensitive-info-demo:1",
                        title="Privacy warning",
                        doc_category="privacy_law",
                        chunk_text="Sensitive information requires consent and safety review.",
                        retrieval_method="hybrid:dense+keyword",
                        similarity_score=0.66,
                        metadata={"warning": "Review sensitive information before storage."},
                    ),
                ]

            settings.enable_dense_retrieval = True
            graph_nodes.retrieve_case_memory_chunks = fake_case_memory_chunks
            graph_nodes.retrieve_authoritative_kb_chunks = fake_authoritative_kb_chunks
            dense_response = client.post("/api/notes/generate", json=payload)
            assert dense_response.status_code == 200, dense_response.text
            dense_data = dense_response.json()
            assert dense_data["retrieved_case_context"][0]["source_ref"].startswith("case_memory:")
            assert "kb:session-note-template-v1:1" in dense_data["retrieved_template_context"]["source_refs"]
            assert dense_data["retrieved_privacy_context"][0]["source_ref"]
        finally:
            settings.enable_rag = original_enable_rag
            settings.enable_dense_retrieval = original_enable_dense
            graph_nodes.retrieve_case_context = original_case_retrieval
            graph_nodes.retrieve_case_memory_chunks = original_case_memory_chunks
            graph_nodes.retrieve_authoritative_kb_chunks = original_authoritative_kb_chunks
            graph_nodes.retrieve_document_template = original_template_retrieval
            graph_nodes.retrieve_privacy_rules = original_privacy_retrieval

        save_payload = {
            "case_id": payload["case_id"],
            "session_number": payload["session_number"],
            "session_date": payload["session_date"],
            "counselor_name": payload["counselor_name"],
            "screen": "summary_draft",
            "form": payload,
            "session_topic": data["session_summary_draft"]["session_theme"]["text"],
            "visible_section_ids": ["main_issue", "session_theme", "session_content"],
            "draft_sections": [
                {
                    "id": "session_content",
                    "title": "상담 내용",
                    "content": data["session_summary_draft"]["session_content"]["text"],
                }
            ],
            "result": data,
        }
        save_response = client.post("/api/notes/drafts", json=save_payload)
        assert save_response.status_code == 200, save_response.text
        saved = save_response.json()
        assert saved["draft_id"]
        assert saved["case_id"] == payload["case_id"]

        load_response = client.get(f"/api/notes/drafts/{saved['draft_id']}")
        assert load_response.status_code == 200, load_response.text
        loaded = load_response.json()
        assert loaded["draft_id"] == saved["draft_id"]
        assert loaded["screen"] == "summary_draft"
        assert loaded["draft_sections"][0]["title"] == "상담 내용"

        recompose_payload = {
            "session_input": payload,
            "session_topic": "진로 불안과 자기비난 사고 점검",
            "visible_section_ids": ["main_issue", "session_theme", "session_content"],
        }
        first_recompose = client.post("/api/notes/recompose", json=recompose_payload)
        assert first_recompose.status_code == 200, first_recompose.text
        first_data = first_recompose.json()
        assert first_data["cache_hit"] is False
        assert first_data["visible_section_ids"] == recompose_payload["visible_section_ids"]
        assert first_data["result"]["session_summary_draft"]["session_content"]["text"]

        second_recompose = client.post("/api/notes/recompose", json=recompose_payload)
        assert second_recompose.status_code == 200, second_recompose.text
        second_data = second_recompose.json()
        assert second_data["cache_hit"] is True
        assert second_data["cache_key"] == first_data["cache_key"]

        supervision_payload = {
            "session_input": payload,
            "session_summary_draft": data["session_summary_draft"],
            "demo_mode": True,
            "report_date": payload["session_date"],
            "client_alias": "가명 은하",
        }
        supervision_response = client.post("/api/notes/supervision-report", json=supervision_payload)
        assert supervision_response.status_code == 200, supervision_response.text
        supervision = supervision_response.json()
        assert supervision["title"] == "개인상담 사례 수퍼비전 보고서 초안"
        assert supervision["reportType"] == "personal_counseling_supervision"
        assert supervision["sections"]
        assert any(section["title"] == "C-1. 상담진행 과정 및 회기주제" for section in supervision["sections"])
        assert supervision["meta"]["institution"] == "리마인드 심리상담센터"
        assert supervision["meta"]["supervisor"] == "이수현 상담심리사 1급"
        assert supervision["aiReview"]["completionChecklist"]
        assert supervision["aiReview"]["missingFields"]
        assert supervision["aiReview"]["demoInputs"]
        assert any(
            block.get("demoValue")
            for section in supervision["sections"]
            for block in section.get("contentBlocks", [])
        )
        assert supervision["aiReview"]["suggestedSupervisionQuestions"]

    print("Smoke test passed: health, note generation, temporary draft storage, cached recomposition, and supervision report generation are working.")


if __name__ == "__main__":
    main()
