"""검증 리포트 프롬프트"""

VERIFICATION_PROMPT = """당신은 상담 기록 검증 전문가입니다.

다음 정보를 기반으로 JSON 형식의 검증 리포트를 생성하세요.

[출력 형식 - 반드시 JSON만 출력]
{{
    "grounded": [
        {{"content": "...", "source": "..."}}
    ],
    "ungrounded": [
        {{"content": "...", "source": "..."}}
    ],
    "sensitive": [
        {{"content": "...", "source": "..."}}
    ],
    "needs_human_judgment": [
        {{"content": "...", "source": "..."}}
    ]
}}

[규칙]
- JSON 외 텍스트 절대 출력 금지
- 각 카테고리 3~7개 항목
- content는 핵심 문장
- source는 반드시 포함 (예: "입력 - 축어록", "입력 - 상담사 메모", "생성 - 구조화", "생성 - 요약")

[검증 기준]
- grounded: 입력(상담사 메모, 축어록)에 직접 근거가 있는 내용
- ungrounded: 입력에 명시되지 않았으나 LLM이 추론/생성한 내용
- sensitive: 개인정보, 민감 진단명 등 주의가 필요한 내용
- needs_human_judgment: 상담사가 직접 확인·수정해야 할 해석적 내용

[입력 원본]
- 상담사 메모: {counselor_memo}
- 축어록: {transcript}

[생성된 정보]
- 구조화 결과: {structured_case}
- 회기 요약: {summary}
"""


def get_verification_prompt(
    counselor_memo: str,
    transcript: str,
    structured_case_dict: dict,
    summary_dict: dict,
) -> str:
    """검증 프롬프트 생성"""
    structured_text = "\n".join(
        [f"- {k}: {v}" for k, v in structured_case_dict.items()]
    )
    summary_text = "\n".join(
        [f"- {k}: {v}" for k, v in summary_dict.items()]
    )
    return VERIFICATION_PROMPT.format(
        counselor_memo=counselor_memo,
        transcript=transcript,
        structured_case=structured_text,
        summary=summary_text,
    )
