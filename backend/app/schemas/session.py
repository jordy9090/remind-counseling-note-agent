"""상담 세션 입력 스키마"""
from typing import Optional
from pydantic import BaseModel


class SessionInput(BaseModel):
    """세션 입력 - 사용자 요청"""
    case_id: str
    session_no: int
    counselor_memo: str
    transcript: str
    prev_summary: Optional[str] = None
