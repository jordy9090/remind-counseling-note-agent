"""검증 노드 - 입력과 생성된 정보를 검증"""
from app.graph.state import GraphState
from app.schemas.verification import VerificationReport, VerificationItem
from app.services.llm import get_llm
from app.prompts.verification_prompt import get_verification_prompt
import json
import re


def verification_node(state: GraphState) -> GraphState:
    """
    입력, 구조화된 정보, 요약을 검증하여 4개 카테고리로 분류
    - input + StructuredCase + SessionSummary → VerificationReport
    """
    input_data = state["input"]
    structured = state["structured"]
    summary = state["summary"]
    
    # 프롬프트 생성
    structured_dict = structured.model_dump()
    summary_dict = summary.model_dump()
    prompt = get_verification_prompt(
        counselor_memo=input_data.counselor_memo,
        transcript=input_data.transcript,
        structured_case_dict=structured_dict,
        summary_dict=summary_dict,
    )
    
    # LLM 호출 (구조화되지 않은 텍스트 응답)
    llm = get_structured_llm(VerificationReport)
    result = llm.invoke(prompt)
    
    # 응답 파싱 - 4개 카테고리로 분류
    state["verification"] = result
    return state


def _parse_verification_response(response_text: str) -> VerificationReport:
    """
    검증 응답 텍스트를 파싱하여 VerificationReport 생성
    """
    grounded = []
    ungrounded = []
    sensitive = []
    needs_human_judgment = []
    
    # 간단한 파싱: 각 섹션 추출
    sections = {
        "grounded": grounded,
        "ungrounded": ungrounded,
        "sensitive": sensitive,
        "needs_human_judgment": needs_human_judgment,
    }
    
    current_section = None
    for line in response_text.split("\n"):
        line = line.strip()
        if not line:
            continue
            
        # 섹션 감지
        if "grounded" in line.lower() and "ungrounded" not in line.lower():
            current_section = "grounded"
        elif "ungrounded" in line.lower():
            current_section = "ungrounded"
        elif "sensitive" in line.lower():
            current_section = "sensitive"
        elif "human" in line.lower() or "judgment" in line.lower():
            current_section = "needs_human_judgment"
        elif current_section and "|" in line:
            # "내용|출처" 형식 파싱
            parts = line.split("|", 1)
            if len(parts) == 2:
                content = parts[0].strip().lstrip("-").strip()
                source = parts[1].strip()
                item = VerificationItem(content=content, source=source)
                sections[current_section].append(item)
        elif current_section and line.startswith(("-", "•", "*")):
            # 항목이 있지만 |가 없는 경우
            content = line.lstrip("-•* ").strip()
            if content:
                item = VerificationItem(content=content, source="생성된 정보")
                sections[current_section].append(item)
    
    # 빈 항목 기본값 추가
    if not grounded:
        grounded.append(VerificationItem(content="기본 상담 정보", source="입력"))
    if not ungrounded:
        ungrounded.append(VerificationItem(content="해석이 필요한 부분", source="생성됨"))
    if not sensitive:
        sensitive.append(VerificationItem(content="민감정보 검토 필요", source="검증"))
    if not needs_human_judgment:
        needs_human_judgment.append(
            VerificationItem(content="상담사 판단 필요", source="검증")
        )
    
    return VerificationReport(
        grounded=grounded,
        ungrounded=ungrounded,
        sensitive=sensitive,
        needs_human_judgment=needs_human_judgment,
    )
