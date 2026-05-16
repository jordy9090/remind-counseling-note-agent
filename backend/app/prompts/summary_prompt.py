"""회기 요약 프롬프트"""

SUMMARY_PROMPT = """당신은 전문 상담사입니다.
구조화된 상담 정보를 바탕으로, 상담사가 검토 후 그대로 쓰거나 수정할 수 있는
회기 요약 '초안'을 작성하세요.

[규칙]
- 각 항목은 2-3문장, 전문적이고 간결한 한국어
- 구조화 정보에 근거한 내용만 작성. 새로운 사실을 추가하거나 추측하지 말 것
- 진단·위험도 평가·임상적 단정을 하지 말 것 (상담사 판단 영역)
- 근거가 부족한 부분은 단정하지 말고 검토가 필요함을 드러내는 표현 사용

구조화된 정보:
{structured_case}

다음 4가지 항목으로 회기 요약 초안을 작성하세요:

1. session_content: 이번 회기에서 다룬 주요 상담내용 (2-3문장)
2. counselor_opinion: 상담자의 소견 — 개입과 내담자 반응에 대한 관찰 (2-3문장)
3. session_summary: 회기 전체를 압축한 요약 (2-3문장)
4. next_counseling_plan: 다음 회기를 위한 추후 개입 계획 (2-3문장)
"""


def get_summary_prompt(structured_case_dict: dict) -> str:
    """요약 프롬프트 생성"""
    structured_text = "\n".join(
        [f"- {k}: {v}" for k, v in structured_case_dict.items()]
    )
    return SUMMARY_PROMPT.format(structured_case=structured_text)
