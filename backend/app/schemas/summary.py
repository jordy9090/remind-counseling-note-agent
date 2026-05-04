"""회기 요약 스키마"""
from pydantic import BaseModel


class SessionSummary(BaseModel):
    """회기 요약 정보"""
    session_content: str  # 상담내용
    counselor_opinion: str  # 상담자소견
    session_summary: str  # 회기요약
    next_counseling_plan: str  # 추후상담계획
