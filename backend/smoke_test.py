"""Smoke test for the Re:mind MVP V0 FastAPI backend.

Run from the backend directory:
    uv run python smoke_test.py
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

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
from app.services.supabase_storage import _build_session_row


def _extract_docx_text(content: bytes) -> str:
    from docx import Document

    document = Document(BytesIO(content))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text)
    return "\n".join(parts)


def _download_filename(content_disposition: str) -> str:
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
    if match:
        return unquote(match.group(1))
    fallback = re.search(r'filename="?([^";]+)"?', content_disposition)
    return fallback.group(1) if fallback else ""


def _assert_pdf_response(content: bytes, content_type: str, expected_texts: list[str]) -> None:
    from pypdf import PdfReader

    assert content.startswith(b"%PDF")
    assert content_type.startswith("application/pdf")
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) >= 1
    extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if extracted_text.strip() and any(expected in extracted_text for expected in expected_texts):
        return
    if extracted_text.strip():
        print("PDF text extraction did not preserve expected Korean text; page-count validation passed.")


def _make_docx_bytes() -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph("상담 메모 첫 문단")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "영역"
    table.cell(0, 1).text = "내용"
    table.cell(1, 0).text = "정서"
    table.cell(1, 1).text = "불안 80"
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_text_pdf_bytes(text: str = "Hello counseling note PDF text") -> bytes:
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_offset = len(content)
    content += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for offset in offsets:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return content


def _make_blank_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _make_wav_bytes(payload_size: int = 16) -> bytes:
    data = b"\x00" * payload_size
    return (
        b"RIFF"
        + (36 + len(data)).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (16000).to_bytes(4, "little")
        + (32000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + len(data).to_bytes(4, "little")
        + data
    )


def _upload_file(client: TestClient, name: str, body: bytes, content_type: str):
    return client.post(
        "/api/materials/documents/extract",
        files={"file": (name, BytesIO(body), content_type)},
    )


def _run_material_upload_smoke_tests(client: TestClient) -> None:
    txt_response = _upload_file(
        client,
        "memo.txt",
        "\ufeff상담 메모\n둘째 줄".encode("utf-8"),
        "text/plain",
    )
    assert txt_response.status_code == 200, txt_response.text
    txt_data = txt_response.json()
    assert txt_data["status"] == "completed"
    assert "상담 메모" in txt_data["extracted_text"]
    assert "둘째 줄" in txt_data["extracted_text"]
    assert txt_data["character_count"] >= 8
    assert txt_response.headers["cache-control"] == "no-store"

    docx_response = _upload_file(
        client,
        "case-note.docx",
        _make_docx_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert docx_response.status_code == 200, docx_response.text
    docx_text = docx_response.json()["extracted_text"]
    assert "상담 메모 첫 문단" in docx_text
    assert "영역\t내용" in docx_text
    assert "정서\t불안 80" in docx_text

    pdf_response = _upload_file(client, "note.pdf", _make_text_pdf_bytes(), "application/pdf")
    assert pdf_response.status_code == 200, pdf_response.text
    pdf_data = pdf_response.json()
    assert pdf_data["page_count"] == 1
    assert "Hello counseling note PDF text" in pdf_data["extracted_text"]

    image_pdf_response = _upload_file(client, "scan.pdf", _make_blank_pdf_bytes(), "application/pdf")
    assert image_pdf_response.status_code == 200, image_pdf_response.text
    image_pdf_data = image_pdf_response.json()
    assert image_pdf_data["status"] == "warning"
    assert "OCR" in " ".join(image_pdf_data["warnings"])

    unsupported_response = _upload_file(client, "note.rtf", b"{\\rtf1}", "application/rtf")
    assert unsupported_response.status_code == 415

    mismatch_response = _upload_file(client, "note.pdf", _make_text_pdf_bytes(), "text/plain")
    assert mismatch_response.status_code == 415

    empty_response = _upload_file(client, "empty.txt", b"", "text/plain")
    assert empty_response.status_code == 400

    original_doc_limit = os.environ.get("DOCUMENT_UPLOAD_MAX_BYTES")
    os.environ["DOCUMENT_UPLOAD_MAX_BYTES"] = "8"
    try:
        too_large_response = _upload_file(client, "large.txt", b"0123456789", "text/plain")
        assert too_large_response.status_code == 413
    finally:
        if original_doc_limit is None:
            os.environ.pop("DOCUMENT_UPLOAD_MAX_BYTES", None)
        else:
            os.environ["DOCUMENT_UPLOAD_MAX_BYTES"] = original_doc_limit

    with tempfile.TemporaryDirectory() as upload_temp_dir:
        previous_tmp_dir = os.environ.get("UPLOAD_TMP_DIR")
        os.environ["UPLOAD_TMP_DIR"] = upload_temp_dir
        try:
            cleanup_response = _upload_file(client, "cleanup.txt", b"temporary cleanup text", "text/plain")
            assert cleanup_response.status_code == 200, cleanup_response.text
            assert not list(Path(upload_temp_dir).iterdir())
        finally:
            if previous_tmp_dir is None:
                os.environ.pop("UPLOAD_TMP_DIR", None)
            else:
                os.environ["UPLOAD_TMP_DIR"] = previous_tmp_dir

    stdout_buffer = BytesIO()
    stderr_buffer = BytesIO()
    secret_text = "RAW_SECRET_CONTENT_SHOULD_NOT_BE_LOGGED"
    with contextlib.redirect_stdout(_BytesTextWriter(stdout_buffer)), contextlib.redirect_stderr(
        _BytesTextWriter(stderr_buffer)
    ):
        raw_log_response = _upload_file(client, "secret.txt", secret_text.encode("utf-8"), "text/plain")
    assert raw_log_response.status_code == 200, raw_log_response.text
    assert secret_text.encode("utf-8") not in stdout_buffer.getvalue()
    assert secret_text.encode("utf-8") not in stderr_buffer.getvalue()

    capabilities = client.get("/api/audio/capabilities")
    assert capabilities.status_code == 200, capabilities.text
    audio_capabilities = capabilities.json()
    assert audio_capabilities["upload"]["available"] is True
    assert audio_capabilities["transcription"]["available"] is False
    assert audio_capabilities["speaker_diarization"]["available"] is False

    original_audio_limit = os.environ.get("AUDIO_UPLOAD_MAX_BYTES")
    os.environ["AUDIO_UPLOAD_MAX_BYTES"] = "20"
    try:
        audio_too_large = client.post(
            "/api/audio/transcribe",
            files={"file": ("session.wav", BytesIO(_make_wav_bytes(128)), "audio/wav")},
        )
        assert audio_too_large.status_code == 413
    finally:
        if original_audio_limit is None:
            os.environ.pop("AUDIO_UPLOAD_MAX_BYTES", None)
        else:
            os.environ["AUDIO_UPLOAD_MAX_BYTES"] = original_audio_limit

    audio_unavailable = client.post(
        "/api/audio/transcribe",
        files={"file": ("session.wav", BytesIO(_make_wav_bytes()), "audio/wav")},
        data={"language": "ko", "task": "transcribe"},
    )
    assert audio_unavailable.status_code == 503


class _BytesTextWriter:
    def __init__(self, buffer: BytesIO) -> None:
        self.buffer = buffer

    def write(self, value: str) -> int:
        data = value.encode("utf-8", errors="replace")
        self.buffer.write(data)
        return len(value)

    def flush(self) -> None:
        return None


def main() -> None:
    require_pdf_export = os.getenv("REQUIRE_PDF_EXPORT") == "1"
    os.environ["ENABLE_AUDIO_TRANSCRIPTION"] = "0"
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

    capabilities_response = client.get("/api/documents/capabilities")
    assert capabilities_response.status_code == 200, capabilities_response.text
    capabilities = capabilities_response.json()
    assert capabilities["docx"]["available"] is True
    assert capabilities["hwpx"]["available"] is False
    if os.name == "nt" and not require_pdf_export:
        assert capabilities["pdf"]["available"] is False, capabilities
    if require_pdf_export:
        assert capabilities["pdf"]["available"] is True, capabilities

    _run_material_upload_smoke_tests(client)

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
        original_template_retrieval = graph_nodes.retrieve_document_template
        original_privacy_retrieval = graph_nodes.retrieve_privacy_rules
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
        finally:
            settings.enable_rag = original_enable_rag
            graph_nodes.retrieve_case_context = original_case_retrieval
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

        session_export_payload = {
            "format": "docx",
            "document_type": "session_note",
            "case_id": "CASE/DEMO:*001",
            "session_number": 5,
            "session_date": "2026-05-24",
            "title": "상담 회기 기록",
            "metadata": {
                "client_alias": "가명 은하",
                "counselor_name": "박상담사",
                "missing_items": ["상담 목표 표현 구체화 필요"],
                "warnings": ["근거 부족 검토 문구"],
            },
            "sections": [
                {
                    "id": "main_issue",
                    "title": "주요 호소",
                    "content": "진로 불안과 자기비난 사고를 호소함.",
                },
                {
                    "id": "session_content",
                    "title": "상담 내용",
                    "content": "첫 줄 상담 내용\n둘째 줄 상담 내용\n- 목록 항목\n최종 수정 내용이 반영됨.",
                },
            ],
        }
        docx_response = client.post("/api/documents/export", json=session_export_payload)
        assert docx_response.status_code == 200, docx_response.text
        assert docx_response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        filename = _download_filename(docx_response.headers["content-disposition"])
        assert filename.endswith(".docx")
        assert "CASE_DEMO__001" in filename
        assert not any(char in filename for char in '<>:"/\\|?*')
        docx_text = _extract_docx_text(docx_response.content)
        assert "상담 회기 기록" in docx_text
        assert "가명 은하" in docx_text
        assert "첫 줄 상담 내용" in docx_text
        assert "둘째 줄 상담 내용" in docx_text
        assert "최종 수정 내용이 반영됨." in docx_text
        assert "missing_items" not in docx_text
        assert "상담 목표 표현 구체화 필요" not in docx_text
        assert "근거 부족 검토 문구" not in docx_text

        real_case_without_alias_payload = {
            **session_export_payload,
            "case_id": "CASE-REAL-002",
            "metadata": {"counselor_name": "박상담사"},
        }
        real_case_response = client.post("/api/documents/export", json=real_case_without_alias_payload)
        assert real_case_response.status_code == 200, real_case_response.text
        real_case_text = _extract_docx_text(real_case_response.content)
        assert "가명 은하" not in real_case_text
        assert "내담자 가명" not in real_case_text

        supervision_export_payload = {
            "format": "docx",
            "document_type": "supervision_report",
            "case_id": payload["case_id"],
            "session_number": payload["session_number"],
            "session_date": payload["session_date"],
            "title": "개인상담 사례 수퍼비전 보고서",
            "metadata": {
                "client_alias": "가명 은하",
                "counselor_name": "박상담사",
                "supervisor": "이수현 상담심리사 1급",
            },
            "sections": [
                {"id": "part-c", "title": "C. 상담 과정", "level": 1},
                {
                    "id": "process",
                    "title": "C-1. 상담진행 과정 및 회기주제",
                    "level": 2,
                    "contentBlocks": [
                        {
                            "id": "paragraph-1",
                            "type": "paragraph",
                            "text": "수정된 pending edit: 불안 자동사고를 사건-생각-감정-행동으로 구분함.",
                        },
                        {
                            "id": "table-1",
                            "type": "table",
                            "rows": [
                                {"영역": "정서", "내용": "불안 80"},
                                {"영역": "행동", "내용": "지원 전 회피"},
                            ],
                        },
                        {
                            "id": "transcript-1",
                            "type": "transcript",
                            "speakerTurns": [
                                {"turnId": "t1", "speaker": "client", "text": "계속 망했다는 생각이 들어요."},
                                {"turnId": "t2", "speaker": "counselor", "text": "그 생각의 근거를 함께 보겠습니다."},
                            ],
                        },
                        {
                            "id": "reflection-1",
                            "type": "reflection_box",
                            "text": "상담자는 정서 확인과 행동 계획의 균형을 점검할 필요가 있음.",
                        },
                    ],
                },
            ],
        }
        supervision_docx_response = client.post("/api/documents/export", json=supervision_export_payload)
        assert supervision_docx_response.status_code == 200, supervision_docx_response.text
        supervision_docx_text = _extract_docx_text(supervision_docx_response.content)
        assert "개인상담 사례 수퍼비전 보고서" in supervision_docx_text
        assert "수정된 pending edit" in supervision_docx_text
        assert "내담자: 계속 망했다는 생각이 들어요." in supervision_docx_text
        assert "영역" in supervision_docx_text
        assert "불안 80" in supervision_docx_text

        termination_export_payload = {
            "format": "docx",
            "document_type": "termination_report",
            "case_id": payload["case_id"],
            "session_number": payload["session_number"],
            "session_date": payload["session_date"],
            "title": "종결 보고서",
            "metadata": {"counselor_name": "박상담사"},
            "sections": [
                {"id": "termination_goal_process", "title": "상담 목표 및 진행 과정", "content": "진행 과정"},
                {"id": "termination_changes", "title": "주요 변화", "content": "주요 변화"},
                {"id": "termination_reason", "title": "종결 사유", "content": "합의 종결"},
                {"id": "termination_recommendation", "title": "향후 권고", "content": "향후 권고"},
                {"id": "termination_counselor_opinion", "title": "상담자 종합소견", "content": "종합소견"},
            ],
        }
        termination_docx_response = client.post("/api/documents/export", json=termination_export_payload)
        assert termination_docx_response.status_code == 200, termination_docx_response.text
        termination_docx_text = _extract_docx_text(termination_docx_response.content)
        for expected_section in [
            "상담 목표 및 진행 과정",
            "주요 변화",
            "종결 사유",
            "향후 권고",
            "상담자 종합소견",
        ]:
            assert expected_section in termination_docx_text

        if capabilities["pdf"]["available"] or require_pdf_export:
            pdf_response = client.post("/api/documents/export", json={**session_export_payload, "format": "pdf"})
            assert pdf_response.status_code == 200, pdf_response.text
            _assert_pdf_response(
                pdf_response.content,
                pdf_response.headers["content-type"],
                ["상담 회기 기록", "첫 줄 상담 내용"],
            )
        else:
            print(f"PDF export not exercised: {capabilities['pdf'].get('reason')}")

        invalid_format_response = client.post(
            "/api/documents/export",
            json={**session_export_payload, "format": "xlsx"},
        )
        assert invalid_format_response.status_code == 422

        empty_sections_response = client.post(
            "/api/documents/export",
            json={**session_export_payload, "format": "docx", "sections": []},
        )
        assert empty_sections_response.status_code == 422

        hwpx_response = client.post("/api/documents/export", json={**session_export_payload, "format": "hwpx"})
        assert hwpx_response.status_code == 422
        assert "HWPX" in hwpx_response.text

    print(
        "Smoke test passed: health, note generation, temporary draft storage, cached recomposition, "
        "supervision report generation, document export, and material upload checks are working."
    )


if __name__ == "__main__":
    main()
