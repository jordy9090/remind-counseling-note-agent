"""요약 노드 - 구조화된 케이스를 회기 요약으로 변환"""
from app.graph.state import GraphState
from app.schemas.summary import SessionSummary
from app.services.llm import get_structured_llm
from app.prompts.summary_prompt import get_summary_prompt


def summary_node(state: GraphState) -> GraphState:
    """
    구조화된 케이스를 바탕으로 회기 요약 생성
    - StructuredCase → SessionSummary
    """
    structured = state["structured"]
    
    # 프롬프트 생성
    structured_dict = structured.model_dump()
    prompt = get_summary_prompt(structured_dict)
    
    # 요약 LLM 호출
    llm = get_structured_llm(SessionSummary)
    result = llm.invoke(prompt)
    
    # 상태 업데이트
    state["summary"] = result
    return state
