"""LangGraph 상태 정의"""
from typing import TypedDict
from app.schemas.session import SessionInput
from app.schemas.structured_case import StructuredCase
from app.schemas.summary import SessionSummary
from app.schemas.verification import VerificationReport


class GraphState(TypedDict):
    """LangGraph의 상태 정의 - 모든 노드가 공유"""
    input: SessionInput
    structured: StructuredCase
    summary: SessionSummary
    verification: VerificationReport
