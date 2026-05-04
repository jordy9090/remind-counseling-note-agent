"""검증 리포트 스키마"""
from typing import List
from pydantic import BaseModel


class VerificationItem(BaseModel):
    """검증 항목"""
    content: str
    source: str  # 어디서 나온 정보인지


class VerificationReport(BaseModel):
    """검증 리포트 - 4가지 분류"""
    grounded: List[VerificationItem]  # 입력에 근거 있는 항목 (초록색)
    ungrounded: List[VerificationItem]  # 근거 부족/추측 항목 (주황색)
    sensitive: List[VerificationItem]  # 민감정보 가능성 (빨강색)
    needs_human_judgment: List[VerificationItem]  # 상담사 직접 판단 필요 (파랑색)
