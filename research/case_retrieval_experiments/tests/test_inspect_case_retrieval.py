from app.services.retrieval import RetrievalChunk
from research.case_retrieval_experiments.scripts.inspect_case_retrieval import (
    artifact_payload,
    build_query,
    dense_rows,
    markdown_review,
    recent_rows,
)


def test_query_uses_existing_deidentification():
    from app.schemas.note import SessionInput

    session = SessionInput(
        case_id="CASE-SYNTH", session_number=2, counselor_memo="연락처 010-1234-5678",
        transcript_text="이메일 test@example.com으로 보냈다", target_document_type="session_note",
    )
    query = build_query(session)
    assert "010-1234-5678" not in query
    assert "test@example.com" not in query
    assert "[PHONE]" in query and "[EMAIL]" in query


def test_dense_artifact_and_review_columns():
    chunk = RetrievalChunk(
        chunk_id="chunk-1", session_id="session-1", session_number=3, session_date="2026-01-01",
        field_type="client_response", similarity_score=0.82, retrieval_method="case_memory_dense",
        source_ref="confirmed_note:note-1:client_response", chunk_text="합성 근거",
    )
    rows = dense_rows([chunk])
    payload = artifact_payload("합성 질의", "CASE-SYNTH", rows, [])
    assert payload["results"][0] == {
        "rank": 1, "session_number": 3, "session_date": "2026-01-01", "field_type": "client_response",
        "retrieval_method": "case_memory_dense", "source_ref": "confirmed_note:note-1:client_response",
        "score": 0.82, "text": "합성 근거",
    }
    review = markdown_review("합성 질의", "CASE-SYNTH", rows, [])
    assert "| Rank | Session | Field | Score | Evidence | Human label | Note |" in review
    assert "GOOD / PARTIAL / BAD" in review


def test_recent_rows_have_no_similarity_score():
    from app.schemas.note import RetrievedCaseContextItem

    rows = recent_rows([RetrievedCaseContextItem(
        source_ref="stored_session_note:s1", session_id="s1", session_number=4, summary="최근 합성 요약"
    )])
    assert rows[0]["similarity_score"] is None
    assert rows[0]["retrieval_method"] == "recent_3_fallback"
