"""검증 프롬프트"""

VERIFICATION_PROMPT = """당신은 상담 기록의 품질 관리 전문가입니다.

입력 원본:
- 상담사 메모: {counselor_memo}
- 축어록: {transcript}

생성된 정보:
{generated_content}

위 생성된 정보를 다음 4가지 기준으로 검증하세요 (한국어):

1. grounded: 입력에 명확하게 근거한 항목들
2. ungrounded: 근거가 약하거나 추측/해석이 포함된 항목들
3. sensitive: 민감한 개인정보나 위험 신호가 포함된 항목들
4. needs_human_judgment: 상담사의 직접 판단이 필요한 항목들

각 카테고리당 5-10개 항목을 "내용|출처" 형식으로 추출하세요."""

def get_verification_prompt(
    counselor_memo: str, 
    transcript: str, 
    structured_case_dict: dict, 
    summary_dict: dict
) -> str:
    """검증 프롬프트 생성"""
    generated_content = f"""
구조화된 정보:
{chr(10).join([f"- {k}: {v}" for k, v in structured_case_dict.items()])}

생성된 요약:
{chr(10).join([f"- {k}: {v}" for k, v in summary_dict.items()])}
"""
    return VERIFICATION_PROMPT.format(
        counselor_memo=counselor_memo,
        transcript=transcript,
        generated_content=generated_content,
    )
