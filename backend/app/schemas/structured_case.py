"""구조화된 케이스 스키마 - 중간 공통 구조"""
from typing import List
from pydantic import BaseModel


class StructuredCase(BaseModel):
    """LLM이 구조화한 상담 정보"""
    basic_info: str  # 기본정보: 케이스ID, 회기번호, 날짜 등
    presenting_problem: str  # 주호소/문제점
    goals: str  # 상담목표
    session_content: str  # 상담내용/과정
    counselor_intervention: str  # 상담자 개입 및 소견
    client_response: str  # 내담자 반응/변화
    assessment: str  # 평가
    next_plan: str  # 추후계획
