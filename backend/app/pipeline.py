"""파이프라인 진입점.

LangGraph 워크플로우(구조화 → 회기요약 → 검증)를 호출하는 단 하나의 함수를
노출한다. Streamlit UI / FastAPI 라우터 모두 이 함수만 쓰면 된다.

OPENAI_API_KEY 가 없거나 USE_STUB=1 이면 sample_data 의 예시 응답을 그대로
돌려주는 스텁 모드로 동작한다. 키 없이도 전체 흐름을 바로 확인할 수 있다.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.schemas.session import SessionInput
from app.schemas.structured_case import StructuredCase
from app.schemas.summary import SessionSummary
from app.schemas.verification import VerificationReport

# backend/app/pipeline.py → repo 루트 (parents[2]) 아래 sample_data
_SAMPLE_OUTPUT = Path(__file__).resolve().parents[2] / "sample_data" / "session_output_001.json"


class PipelineResult:
    """파이프라인 3단계 산출물 묶음"""

    def __init__(
        self,
        structured: StructuredCase,
        summary: SessionSummary,
        verification: VerificationReport,
        stub: bool,
    ) -> None:
        self.structured = structured
        self.summary = summary
        self.verification = verification
        self.stub = stub  # 스텁 응답인지 여부 (UI 안내 배너용)


def _run_stub() -> PipelineResult:
    """sample_data 의 예시 출력을 스키마로 로드해 반환"""
    data = json.loads(_SAMPLE_OUTPUT.read_text(encoding="utf-8"))
    return PipelineResult(
        structured=StructuredCase(**data["structured"]),
        summary=SessionSummary(**data["summary"]),
        verification=VerificationReport(**data["verification"]),
        stub=True,
    )


def _run_graph(session_input: SessionInput) -> PipelineResult:
    """실제 LangGraph 워크플로우 실행 (OpenAI 호출)"""
    # 그래프/LLM 임포트는 키가 있을 때만 로드 (스텁 모드 import 비용 회피)
    from app.graph.state import GraphState
    from app.graph.workflow import app as workflow

    initial_state: GraphState = {
        "input": session_input,
        "structured": None,
        "summary": None,
        "verification": None,
    }
    result = workflow.invoke(initial_state)
    return PipelineResult(
        structured=result["structured"],
        summary=result["summary"],
        verification=result["verification"],
        stub=False,
    )


def run_pipeline(session_input: SessionInput) -> PipelineResult:
    """입력 → 구조화 → 회기요약 → 검증 리포트.

    스텁 모드면 예시 응답을, 아니면 LangGraph 결과를 반환한다.
    """
    if settings.stub_mode:
        return _run_stub()
    return _run_graph(session_input)
