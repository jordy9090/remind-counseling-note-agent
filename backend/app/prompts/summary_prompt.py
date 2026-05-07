"""회기 요약 프롬프트"""

SUMMARY_PROMPT = """당신은 전문 상담사입니다.
구조화된 상담 정보를 바탕으로 회기 요약을 작성하세요.

[규칙]
- 각 항목은 2-3문장
- 전문적이고 객관적인 한국어

구조화된 정보:
{structured_case}

다음 4가지 항목으로 회기 요약을 작성하세요:

1. session_content: 이번 회기에서 다룬 주요 상담내용 (2-3문장)
2. counselor_opinion: 상담자의 전문적 소견 및 평가 (2-3문장)
3. session_summary: 회기의 전체적인 요약 (2-3문장)
4. next_counseling_plan: 다음 회기를 위한 상담 계획 (2-3문장)
"""


def get_summary_prompt(structured_case_dict: dict) -> str:
    """요약 프롬프트 생성"""
    structured_text = "\n".join(
        [f"- {k}: {v}" for k, v in structured_case_dict.items()]
    )
    return SUMMARY_PROMPT.format(structured_case=structured_text)
