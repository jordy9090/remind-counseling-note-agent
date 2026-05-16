"""검증 노드 - 입력과 생성된 정보를 검증"""
from app.graph.state import GraphState
from app.prompts.verification_prompt import get_verification_prompt
from app.schemas.verification import VerificationReport
from app.services.llm import get_structured_llm


def verification_node(state: GraphState) -> GraphState:
    """
    입력, 구조화된 정보, 요약을 검증하여 4개 카테고리로 분류
    - input + StructuredCase + SessionSummary → VerificationReport
      (근거 있음 / 근거 부족·추론 / 민감정보 / 상담사 판단 필요)
    """
    input_data = state["input"]
    structured = state["structured"]
    summary = state["summary"]

    prompt = get_verification_prompt(
        counselor_memo=input_data.counselor_memo,
        transcript=input_data.transcript,
        structured_case_dict=structured.model_dump(),
        summary_dict=summary.model_dump(),
    )

    # 구조화된 출력으로 4개 카테고리를 그대로 받는다
    llm = get_structured_llm(VerificationReport)
    state["verification"] = llm.invoke(prompt)
    return state
