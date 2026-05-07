"""상담 정보 구조화 프롬프트"""

STRUCTURE_PROMPT = """당신은 전문 상담사입니다.
다음 상담 정보를 구조화하세요.

[규칙]
- 모든 필드는 string
- 정보 없으면 "정보 없음"

입력:
- 상담사 메모: {counselor_memo}
- 축어록(전사): {transcript}
- 이전 회기 요약: {prev_summary}

다음 8가지 필드로 정보를 구조화하세요 (한국어로 작성):

1. basic_info: 케이스ID, 회기번호, 상담 기본정보
2. presenting_problem: 내담자의 주호소/문제점
3. goals: 이번 회기의 상담목표
4. session_content: 상담 중 진행된 내용과 과정
5. counselor_intervention: 상담자의 개입 방식과 소견
6. client_response: 내담자의 반응과 변화
7. assessment: 상담사의 평가
8. next_plan: 추후 상담 계획

모든 필드를 채우되, 정보가 없으면 "정보 없음"으로 표시하세요.
"""


def get_structure_prompt(counselor_memo: str, transcript: str, prev_summary: str = None) -> str:
    """구조화 프롬프트 생성"""
    prev_summary_text = prev_summary if prev_summary else "없음"
    return STRUCTURE_PROMPT.format(
        counselor_memo=counselor_memo,
        transcript=transcript,
        prev_summary=prev_summary_text,
    )
