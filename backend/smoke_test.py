"""Smoke test for the Re:mind MVP V0 FastAPI backend.

Run from the backend directory:
    uv run python smoke_test.py
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings, validate_runtime_security
from app.graph import nodes as graph_nodes
from app.main import app
from app.schemas.note import (
    ConfirmGeneratedNoteRequest,
    GenerateNoteResponse,
    RetrievedCaseContextItem,
    RetrievedEvidenceItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    SessionInput,
)
from app.services.deidentification import deidentify_text
from app.services.embeddings import (
    EmbeddingError,
    clear_embedding_cache,
    content_hash,
    embed_query,
    embedding_cache_stats,
    get_embedding_provider,
)
from app.services.retrieval import RetrievalChunk
from app.services import supabase_storage as supabase_storage_module
from app.services.supabase_storage import (
    ConfirmedNoteContext,
    NoteConfirmationError,
    _attach_embeddings,
    _build_session_row,
    _case_memory_rows_from_confirmed_note,
    confirm_generated_note,
)


def main() -> None:
    settings.use_stub = True
    settings.openai_api_key = None
    settings.enable_persistence = False
    settings.enable_rag = False
    settings.supabase_url = None
    settings.supabase_service_role_key = None
    settings.supabase_service_key = None
    settings.save_raw_input = False
    settings.enable_case_memory = False
    settings.runtime_environment = "test"
    settings.remind_preview_api_token = "test-preview-token"
    settings.remind_preview_actor = "test-preview-actor"
    settings.remind_allow_local_bypass = False

    original_runtime = settings.runtime_environment
    original_persistence = settings.enable_persistence
    original_case_memory = settings.enable_case_memory
    original_preview_token = settings.remind_preview_api_token
    original_real_auth = settings.enable_real_user_auth
    original_local_bypass = settings.remind_allow_local_bypass
    try:
        settings.runtime_environment = "production"
        settings.enable_persistence = True
        settings.enable_case_memory = False
        settings.remind_preview_api_token = None
        settings.enable_real_user_auth = False
        settings.remind_allow_local_bypass = False
        try:
            validate_runtime_security()
        except RuntimeError as error:
            assert "ENABLE_PERSISTENCE=1" in str(error)
        else:
            raise AssertionError("Production persistence must fail without preview auth or real auth.")

        settings.enable_persistence = False
        settings.enable_case_memory = True
        try:
            validate_runtime_security()
        except RuntimeError as error:
            assert "ENABLE_CASE_MEMORY=1" in str(error)
        else:
            raise AssertionError("Production case memory must fail without preview auth or real auth.")

        settings.remind_preview_api_token = "test-preview-token"
        validate_runtime_security()
    finally:
        settings.runtime_environment = original_runtime
        settings.enable_persistence = original_persistence
        settings.enable_case_memory = original_case_memory
        settings.remind_preview_api_token = original_preview_token
        settings.enable_real_user_auth = original_real_auth
        settings.remind_allow_local_bypass = original_local_bypass

    root = Path(__file__).resolve().parents[1]
    for migration_path in (root / "supabase" / "migrations").glob("*.sql"):
        sql = migration_path.read_text(encoding="utf-8").lower()
        assert "drop table" not in sql
        assert "drop schema" not in sql
        assert "truncate " not in sql
        assert "delete from" not in sql

    assert content_hash("  a\nb  ", model="model-a") == content_hash("a b", model="model-a")
    assert content_hash("a b", model="model-a") != content_hash("a b", model="model-b")
    settings.use_stub = False
    settings.openai_api_key = None
    try:
        get_embedding_provider()
    except EmbeddingError:
        pass
    else:
        raise AssertionError("Dense retrieval must fail closed when no embedding provider is configured.")
    settings.use_stub = True

    original_cache_ttl = settings.embedding_cache_ttl_seconds
    original_cache_max = settings.embedding_cache_max_entries
    original_cache_disabled = settings.disable_embedding_cache
    original_embedding_model = settings.embedding_model
    try:
        clear_embedding_cache()
        settings.disable_embedding_cache = False
        settings.embedding_cache_ttl_seconds = 1
        settings.embedding_cache_max_entries = 2
        settings.embedding_model = "test-embedding-model-a"
        first_embedding = embed_query("same normalized query")
        assert embedding_cache_stats()["misses"] == 1
        second_embedding = embed_query(" same   normalized   query ")
        assert first_embedding == second_embedding
        assert embedding_cache_stats()["hits"] == 1
        settings.embedding_model = "test-embedding-model-b"
        embed_query("same normalized query")
        assert embedding_cache_stats()["misses"] == 2
        time.sleep(1.05)
        embed_query("same normalized query")
        assert embedding_cache_stats()["misses"] == 3
    finally:
        clear_embedding_cache()
        settings.embedding_cache_ttl_seconds = original_cache_ttl
        settings.embedding_cache_max_entries = original_cache_max
        settings.disable_embedding_cache = original_cache_disabled
        settings.embedding_model = original_embedding_model

    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json() == {"status": "ok"}
    preview_headers = {"X-Remind-Preview-Token": "test-preview-token"}

    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TEMP_DRAFT_DIR"] = temp_dir
        os.environ["RECOMPOSE_CACHE_DIR"] = str(Path(temp_dir) / "recompose")

        sample_path = Path(__file__).resolve().parents[1] / "sample_data" / "session_input_001.json"
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        missing_token = client.post("/api/notes/generate", json=payload)
        assert missing_token.status_code == 401
        invalid_token = client.post("/api/notes/generate", json=payload, headers={"X-Remind-Preview-Token": "wrong"})
        assert invalid_token.status_code == 401
        assert client.get("/api/notes/drafts").status_code == 401

        pii_text = "이름: 홍길동, 연락처 010-1234-5678, email test@example.com, 학번 2026123456"
        masked_text, pii_candidates = deidentify_text(pii_text, source="counselor_memo")
        assert "010-1234-5678" not in masked_text
        assert "test@example.com" not in masked_text
        assert "홍길동" not in masked_text
        assert "[STUDENT_ID]" in masked_text
        assert pii_candidates

        response = client.post("/api/notes/generate", json=payload, headers=preview_headers)
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

        pii_payload = {
            **payload,
            "counselor_memo": pii_text,
            "transcript_text": "Cl: 서울시 강남구 테헤란로에 살고 010-9999-0000으로 연락 가능해요.",
        }
        pii_response = client.post("/api/notes/generate", json=pii_payload, headers=preview_headers)
        assert pii_response.status_code == 200, pii_response.text
        pii_data = pii_response.json()
        serialized_sanitized = json.dumps(pii_data["sanitized_input"], ensure_ascii=False)
        assert "010-1234-5678" not in serialized_sanitized
        assert "010-9999-0000" not in serialized_sanitized
        assert "test@example.com" not in serialized_sanitized
        assert "홍길동" not in serialized_sanitized

        memory_request = ConfirmGeneratedNoteRequest(
            note_id="00000000-0000-0000-0000-000000000011",
            confirmed_note={
                "sections": {
                    "session_theme": pii_text,
                    "client_response": "Client reported anxiety decreasing after small next actions.",
                    "next_plan": "Review student id 2026123456 only after masking.",
                }
            },
            counselor_edited=True,
            create_case_memory=True,
        )
        memory_context = ConfirmedNoteContext(
            note_id=memory_request.note_id,
            case_id=payload["case_id"],
            session_id="00000000-0000-0000-0000-000000000012",
            session_number=payload["session_number"],
            session_date=payload["session_date"],
            counselor_id="test-preview-actor",
        )
        memory_rows = _case_memory_rows_from_confirmed_note(memory_request, memory_context)
        serialized_memory_rows = json.dumps(memory_rows, ensure_ascii=False)
        assert "010-1234-5678" not in serialized_memory_rows
        assert "test@example.com" not in serialized_memory_rows
        assert "2026123456" not in serialized_memory_rows
        assert "[PHONE]" in serialized_memory_rows
        assert "[EMAIL]" in serialized_memory_rows
        assert "[STUDENT_ID]" in serialized_memory_rows
        assert all(row["source_note_id"] == memory_request.note_id for row in memory_rows)
        assert all(row["source_ref"].startswith(f"confirmed_note:{memory_request.note_id}:") for row in memory_rows)

        original_dense = settings.enable_dense_retrieval
        original_stub = settings.use_stub
        original_api_key = settings.openai_api_key
        try:
            settings.enable_dense_retrieval = True
            settings.use_stub = False
            settings.openai_api_key = None
            unavailable_rows = [row.copy() for row in memory_rows]
            assert _attach_embeddings(unavailable_rows) == 0
            assert all("embedding" not in row for row in unavailable_rows)

            settings.use_stub = True
            embedded_rows = [row.copy() for row in memory_rows]
            assert _attach_embeddings(embedded_rows) == len(embedded_rows)
            assert all(len(row["embedding"]) == settings.embedding_dimension for row in embedded_rows)
        finally:
            settings.enable_dense_retrieval = original_dense
            settings.use_stub = original_stub
            settings.openai_api_key = original_api_key

        persist_without_supabase = client.post("/api/notes/generate", json={**payload, "persist": True}, headers=preview_headers)
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
            rag_response = client.post("/api/notes/generate", json=payload, headers=preview_headers)
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
            dense_response = client.post("/api/notes/generate", json=payload, headers=preview_headers)
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

        confirm_without_persistence = client.post(
            "/api/notes/confirm",
            json={
                "note_id": "00000000-0000-0000-0000-000000000001",
                "confirmed_note": data["confirmed_session_note"],
                "counselor_edited": True,
                "create_case_memory": True,
            },
            headers=preview_headers,
        )
        assert confirm_without_persistence.status_code == 409
        spoofed_confirm = client.post(
            "/api/notes/confirm",
            json={
                "note_id": "00000000-0000-0000-0000-000000000001",
                "case_id": payload["case_id"],
                "confirmed_by": "spoofed-client",
                "confirmed_note": data["confirmed_session_note"],
            },
            headers=preview_headers,
        )
        assert spoofed_confirm.status_code == 422
        try:
            confirm_generated_note(
                ConfirmGeneratedNoteRequest(
                    note_id="00000000-0000-0000-0000-000000000001",
                    confirmed_note=data["confirmed_session_note"],
                ),
                actor="test-preview-actor",
            )
        except NoteConfirmationError as error:
            assert error.status_code == 409
        else:
            raise AssertionError("Confirmation must be server-validated and reject disabled persistence.")

        original_storage = supabase_storage_module.storage
        original_enable_persistence = settings.enable_persistence
        original_enable_case_memory = settings.enable_case_memory
        original_supabase_url = settings.supabase_url
        original_supabase_key = settings.supabase_service_role_key
        original_enable_dense = settings.enable_dense_retrieval
        try:
            fake_storage = FakeConfirmationStorage()
            supabase_storage_module.storage = fake_storage  # type: ignore[assignment]
            settings.enable_persistence = True
            settings.enable_case_memory = True
            settings.supabase_url = "https://example.supabase.co"
            settings.supabase_service_role_key = "fake-service-key"
            settings.enable_dense_retrieval = False

            confirm_payload = ConfirmGeneratedNoteRequest(
                note_id=fake_storage.note_id,
                confirmed_note={
                    "sections": {
                        "session_theme": "Career anxiety and self-critical thoughts.",
                        "client_response": "Anxiety decreased after smaller actions.",
                        "next_plan": "Review one thought record next session.",
                    }
                },
            )
            first_confirm = confirm_generated_note(confirm_payload, actor="test-preview-actor")
            assert first_confirm.confirmation_status == "confirmed"
            assert first_confirm.memory_chunk_count == 3
            assert len(fake_storage.case_memory_chunks) == 3
            first_theme_hash = fake_storage.memory_by_field("session_theme")["content_hash"]

            second_confirm = confirm_generated_note(confirm_payload, actor="test-preview-actor")
            assert second_confirm.memory_chunk_count == 3
            assert len(fake_storage.case_memory_chunks) == 3
            assert fake_storage.memory_by_field("session_theme")["content_hash"] == first_theme_hash

            try:
                confirm_generated_note(
                    ConfirmGeneratedNoteRequest(
                        note_id=fake_storage.note_id,
                        confirmed_note={
                            "sections": {
                                "session_theme": "Unmarked conflicting confirmation.",
                                "client_response": "Anxiety decreased after smaller actions.",
                                "next_plan": "Review one thought record next session.",
                            }
                        },
                        counselor_edited=False,
                    ),
                    actor="test-preview-actor",
                )
            except NoteConfirmationError as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Changed reconfirmation without counselor_edited=true must be rejected.")

            fake_storage.memory_by_field("session_theme")["unchanged_marker"] = "keep"
            revised_confirm = confirm_generated_note(
                ConfirmGeneratedNoteRequest(
                    note_id=fake_storage.note_id,
                    confirmed_note={
                        "sections": {
                            "session_theme": "Revised career anxiety theme.",
                            "client_response": "Anxiety decreased after smaller actions.",
                            "next_plan": "Review one thought record next session.",
                        }
                    },
                ),
                actor="test-preview-actor",
            )
            assert revised_confirm.memory_chunk_count == 3
            assert len(fake_storage.case_memory_chunks) == 3
            assert fake_storage.memory_by_field("session_theme")["content_hash"] != first_theme_hash
            assert fake_storage.memory_by_field("session_theme")["unchanged_marker"] == "keep"
            assert fake_storage.duplicate_source_ref_groups() == 0

            try:
                confirm_generated_note(
                    ConfirmGeneratedNoteRequest(
                        note_id="00000000-0000-0000-0000-00000000ffff",
                        confirmed_note=confirm_payload.confirmed_note,
                    ),
                    actor="test-preview-actor",
                )
            except NoteConfirmationError as error:
                assert error.status_code == 404
            else:
                raise AssertionError("Nonexistent notes must be rejected.")

            fake_storage.drop_session = True
            try:
                confirm_generated_note(confirm_payload, actor="test-preview-actor")
            except NoteConfirmationError as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Notes with missing sessions must be rejected.")
        finally:
            supabase_storage_module.storage = original_storage  # type: ignore[assignment]
            settings.enable_persistence = original_enable_persistence
            settings.enable_case_memory = original_enable_case_memory
            settings.supabase_url = original_supabase_url
            settings.supabase_service_role_key = original_supabase_key
            settings.enable_dense_retrieval = original_enable_dense

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
        save_response = client.post("/api/notes/drafts", json=save_payload, headers=preview_headers)
        assert save_response.status_code == 200, save_response.text
        saved = save_response.json()
        assert saved["draft_id"]
        assert saved["case_id"] == payload["case_id"]

        load_response = client.get(f"/api/notes/drafts/{saved['draft_id']}", headers=preview_headers)
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
        first_recompose = client.post("/api/notes/recompose", json=recompose_payload, headers=preview_headers)
        assert first_recompose.status_code == 200, first_recompose.text
        first_data = first_recompose.json()
        assert first_data["cache_hit"] is False
        assert first_data["visible_section_ids"] == recompose_payload["visible_section_ids"]
        assert first_data["result"]["session_summary_draft"]["session_content"]["text"]

        second_recompose = client.post("/api/notes/recompose", json=recompose_payload, headers=preview_headers)
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
        supervision_response = client.post("/api/notes/supervision-report", json=supervision_payload, headers=preview_headers)
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


class FakeConfirmationStorage:
    def __init__(self) -> None:
        self.note_id = "00000000-0000-0000-0000-000000000101"
        self.session_id = "00000000-0000-0000-0000-000000000102"
        self.case_id = "CASE-DEMO-001"
        self.drop_session = False
        self.generated_notes = [
            {
                "id": self.note_id,
                "case_id": self.case_id,
                "session_id": self.session_id,
                "note_type": "session_note",
                "draft_json": {"synthetic": True},
                "confirmed_json": {},
                "confirmation_status": "draft",
            }
        ]
        self.sessions = [
            {
                "id": self.session_id,
                "case_id": self.case_id,
                "session_number": 5,
                "session_date": "2026-05-24",
                "session_title": "Synthetic confirmation test",
            }
        ]
        self.cases = [{"id": self.case_id, "case_alias": self.case_id, "counselor_id": "test-preview-actor"}]
        self.case_memory_chunks: list[dict[str, object]] = []

    def maybe_single(self, table: str, query: dict[str, str | int]) -> dict[str, object] | None:
        rows = self.select(table, query)
        return rows[0] if rows else None

    def select(self, table: str, query: dict[str, str | int]) -> list[dict[str, object]]:
        if table == "generated_notes":
            return self._filter_by_eq(self.generated_notes, "id", str(query.get("id") or ""))
        if table == "sessions":
            if self.drop_session:
                return []
            return self._filter_by_eq(self.sessions, "id", str(query.get("id") or ""))
        if table == "cases":
            return self._filter_by_eq(self.cases, "id", str(query.get("id") or ""))
        if table == "case_memory_chunks":
            source_note_id = self._eq_value(str(query.get("source_note_id") or ""))
            return [row for row in self.case_memory_chunks if row.get("source_note_id") == source_note_id]
        return []

    def update(
        self,
        table: str,
        values: dict[str, object],
        *,
        query: dict[str, str | int],
        return_representation: bool = True,
    ) -> list[dict[str, object]]:
        rows = self.select(table, query)
        for row in rows:
            row.update(values)
        return rows if return_representation else []

    def upsert(self, table: str, rows: list[dict[str, object]], *, on_conflict: str) -> list[dict[str, object]]:
        assert table == "case_memory_chunks"
        assert on_conflict == "source_note_id,field_type"
        result = []
        for row in rows:
            existing = next(
                (
                    current
                    for current in self.case_memory_chunks
                    if current.get("source_note_id") == row.get("source_note_id")
                    and current.get("field_type") == row.get("field_type")
                ),
                None,
            )
            if existing:
                existing.update(row)
                result.append(existing)
            else:
                stored = dict(row)
                self.case_memory_chunks.append(stored)
                result.append(stored)
        return result

    def memory_by_field(self, field_type: str) -> dict[str, object]:
        for row in self.case_memory_chunks:
            if row.get("field_type") == field_type:
                return row
        raise AssertionError(f"Missing memory row for {field_type}")

    def duplicate_source_ref_groups(self) -> int:
        counts: dict[object, int] = {}
        for row in self.case_memory_chunks:
            counts[row.get("source_ref")] = counts.get(row.get("source_ref"), 0) + 1
        return sum(1 for count in counts.values() if count > 1)

    def _filter_by_eq(self, rows: list[dict[str, object]], key: str, condition: str) -> list[dict[str, object]]:
        value = self._eq_value(condition)
        return [row for row in rows if row.get(key) == value]

    @staticmethod
    def _eq_value(condition: str) -> str:
        return condition[3:] if condition.startswith("eq.") else condition


if __name__ == "__main__":
    main()
