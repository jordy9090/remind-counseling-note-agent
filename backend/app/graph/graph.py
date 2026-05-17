"""LangGraph wiring for the Re:mind MVP V0 six-agent workflow."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    generate_summary,
    map_evidence,
    sanitize_input,
    structure_session,
    transform_document_preview,
    verify_output,
)
from app.schemas.note import (
    DocumentTransformPreview,
    EvidenceMappedData,
    GenerateNoteResponse,
    SanitizedInput,
    SessionInput,
    SessionSummaryDraft,
    StructuredCaseData,
    VerificationReport,
)


class NoteGraphState(TypedDict, total=False):
    session_input: SessionInput
    sanitized_input: SanitizedInput
    structured_case_data: StructuredCaseData
    evidence_mapped_data: EvidenceMappedData
    session_summary_draft: SessionSummaryDraft
    verification_report: VerificationReport
    document_transform_preview: DocumentTransformPreview
    confirmed_session_note: dict[str, Any]
    stub: bool


def create_note_graph():
    workflow = StateGraph(NoteGraphState)
    workflow.add_node("sanitize_input", sanitize_input)
    workflow.add_node("structure_session", structure_session)
    workflow.add_node("map_evidence", map_evidence)
    workflow.add_node("generate_summary", generate_summary)
    workflow.add_node("verify_output", verify_output)
    workflow.add_node("transform_document_preview", transform_document_preview)

    workflow.set_entry_point("sanitize_input")
    workflow.add_edge("sanitize_input", "structure_session")
    workflow.add_edge("structure_session", "map_evidence")
    workflow.add_edge("map_evidence", "generate_summary")
    workflow.add_edge("generate_summary", "verify_output")
    workflow.add_edge("verify_output", "transform_document_preview")
    workflow.add_edge("transform_document_preview", END)
    return workflow.compile()


note_graph = create_note_graph()


def run_note_pipeline(session_input: SessionInput) -> GenerateNoteResponse:
    state = note_graph.invoke({"session_input": session_input})
    return GenerateNoteResponse(
        sanitized_input=state["sanitized_input"],
        structured_case_data=state["structured_case_data"],
        evidence_mapped_data=state["evidence_mapped_data"],
        session_summary_draft=state["session_summary_draft"],
        verification_report=state["verification_report"],
        document_transform_preview=state["document_transform_preview"],
        confirmed_session_note=state.get("confirmed_session_note", {}),
        stub=bool(state.get("stub", False)),
    )
