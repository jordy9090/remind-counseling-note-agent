"""LangGraph wiring for the Re:mind V1 retrieval-aware workflow."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    conditional_revision,
    formulate_retrieval_query,
    fuse_and_rerank,
    generate_summary,
    map_evidence,
    retrieve_authoritative_kb,
    retrieve_case_memory,
    sanitize_input,
    structure_session,
    transform_document_preview,
    verify_output,
)
from app.schemas.note import (
    DocumentTransformPreview,
    EvidenceMappedData,
    GenerateNoteResponse,
    RetrievedCaseContextItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    RetrievalReport,
    SanitizedInput,
    SessionInput,
    SessionSummaryDraft,
    StructuredCaseData,
    VerificationReport,
)


class NoteGraphState(TypedDict, total=False):
    session_input: SessionInput
    requested_section_ids: list[str]
    session_topic: str
    sanitized_input: SanitizedInput
    retrieval_query: str
    retrieved_case_context: list[RetrievedCaseContextItem]
    retrieved_case_memory_chunks: list[Any]
    retrieved_authoritative_kb_chunks: list[Any]
    retrieved_template_context: RetrievedTemplateContext | None
    retrieved_privacy_context: list[RetrievedPrivacyRule]
    retrieval_report: RetrievalReport
    structured_case_data: StructuredCaseData
    evidence_mapped_data: EvidenceMappedData
    session_summary_draft: SessionSummaryDraft
    verification_report: VerificationReport
    revision_attempted: bool
    revision_needs_reverify: bool
    revision_reason: str
    document_transform_preview: DocumentTransformPreview
    confirmed_session_note: dict[str, Any]
    stub: bool


def _route_after_revision(state: NoteGraphState) -> str:
    return "reverify" if state.get("revision_needs_reverify") else "preview"


def create_note_graph():
    workflow = StateGraph(NoteGraphState)
    workflow.add_node("sanitize_input", sanitize_input)
    workflow.add_node("formulate_retrieval_query", formulate_retrieval_query)
    workflow.add_node("retrieve_case_memory", retrieve_case_memory)
    workflow.add_node("retrieve_authoritative_kb", retrieve_authoritative_kb)
    workflow.add_node("fuse_and_rerank", fuse_and_rerank)
    workflow.add_node("structure_session", structure_session)
    workflow.add_node("map_evidence", map_evidence)
    workflow.add_node("generate_summary", generate_summary)
    workflow.add_node("verify_output", verify_output)
    workflow.add_node("conditional_revision", conditional_revision)
    workflow.add_node("transform_document_preview", transform_document_preview)

    workflow.set_entry_point("sanitize_input")
    workflow.add_edge("sanitize_input", "formulate_retrieval_query")
    workflow.add_edge("formulate_retrieval_query", "retrieve_case_memory")
    workflow.add_edge("retrieve_case_memory", "retrieve_authoritative_kb")
    workflow.add_edge("retrieve_authoritative_kb", "fuse_and_rerank")
    workflow.add_edge("fuse_and_rerank", "structure_session")
    workflow.add_edge("structure_session", "map_evidence")
    workflow.add_edge("map_evidence", "generate_summary")
    workflow.add_edge("generate_summary", "verify_output")
    workflow.add_edge("verify_output", "conditional_revision")
    workflow.add_conditional_edges(
        "conditional_revision",
        _route_after_revision,
        {
            "reverify": "verify_output",
            "preview": "transform_document_preview",
        },
    )
    workflow.add_edge("transform_document_preview", END)
    return workflow.compile()


note_graph = create_note_graph()


def run_note_pipeline(
    session_input: SessionInput,
    requested_section_ids: list[str] | None = None,
    session_topic: str = "",
) -> GenerateNoteResponse:
    initial_state: NoteGraphState = {"session_input": session_input}
    if requested_section_ids is not None:
        initial_state["requested_section_ids"] = requested_section_ids
    if session_topic:
        initial_state["session_topic"] = session_topic
    state = note_graph.invoke(initial_state)
    confirmed_session_note = state.get("confirmed_session_note") or _build_confirmed_session_note(state)
    return GenerateNoteResponse(
        sanitized_input=state["sanitized_input"],
        structured_case_data=state["structured_case_data"],
        evidence_mapped_data=state["evidence_mapped_data"],
        session_summary_draft=state["session_summary_draft"],
        verification_report=state["verification_report"],
        document_transform_preview=state["document_transform_preview"],
        confirmed_session_note=confirmed_session_note,
        retrieved_case_context=state.get("retrieved_case_context") or [],
        retrieved_template_context=state.get("retrieved_template_context"),
        retrieved_privacy_context=state.get("retrieved_privacy_context") or [],
        retrieval_report=state.get("retrieval_report") or RetrievalReport(),
        stub=bool(state.get("stub", False)),
    )


def _build_confirmed_session_note(state: NoteGraphState) -> dict[str, Any]:
    summary = state["session_summary_draft"]
    verification = state["verification_report"]
    preview = state["document_transform_preview"]

    return {
        "status": "draft_requires_counselor_confirmation",
        "case_id": summary.session_info.case_id,
        "session_number": summary.session_info.session_number,
        "session_date": summary.session_info.session_date,
        "sections": {
            "session_theme": summary.session_theme.text,
            "presenting_problem": summary.presenting_problem.text,
            "session_content": summary.session_content.text,
            "counselor_intervention": summary.counselor_intervention.text,
            "client_response": summary.client_response.text,
            "reflection": summary.reflection.text,
            "next_plan": summary.next_plan.text,
        },
        "review_summary": {
            "grounded_count": len(verification.grounded_items),
            "weakly_grounded_count": len(verification.weakly_grounded_items),
            "risky_claim_count": len(verification.unsupported_or_risky_claims),
            "sensitive_info_count": len(verification.sensitive_info_items),
            "counselor_review_count": len(verification.requires_counselor_review),
        },
        "document_preview_notice": preview.notice,
    }
