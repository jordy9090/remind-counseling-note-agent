"""구조화 노드 - 입력을 구조화된 케이스로 변환"""
from app.graph.state import GraphState
from app.schemas.structured_case import StructuredCase
from app.services.llm import get_structured_llm
from app.prompts.structure_prompt import get_structure_prompt


def structure_node(state: GraphState) -> GraphState:
    """
    입력 정보를 구조화된 케이스로 변환
    - 상담사 메모 + 축어록 + 이전 요약 → StructuredCase
    """
    input_data = state["input"]
    
    # 프롬프트 생성
    prompt = get_structure_prompt(
        counselor_memo=input_data.counselor_memo,
        transcript=input_data.transcript,
        prev_summary=input_data.prev_summary,
    )
    
    # 구조화된 LLM 호출 (response_schema 강제)
    llm = get_structured_llm(StructuredCase)
    result = llm.invoke(prompt)
    
    # 상태 업데이트
    state["structured"] = result
    return state
