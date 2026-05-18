# API 계약서

MVP V0의 primary backend API는 FastAPI에서 제공합니다.

## 1. Health Check

```text
GET /api/health
```

응답:

```json
{
  "status": "ok"
}
```

참고: legacy 호환을 위해 `GET /health`도 유지됩니다.

## 2. 회기요약 생성

```text
POST /api/notes/generate
```

### 요청

`backend/app/schemas/note.py`의 `SessionInput`과 일치합니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "Counselor A",
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
  "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_session_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸.",
  "counseling_goal": "진로 선택 과정에서 자기이해를 높이고 실행 가능한 준비 계획을 세움.",
  "psychological_test_summary": "",
  "key_issue_tags": ["진로불안", "자기비난", "취업준비"],
  "nonverbal_notes": ""
}
```

호환 입력:

- `session_no`는 `session_number` alias로 받을 수 있습니다.
- `transcript`는 `transcript_text` alias로 받을 수 있습니다.
- `prev_summary`는 `previous_session_summary` alias로 받을 수 있습니다.

### 응답

`backend/app/schemas/note.py`의 `GenerateNoteResponse`와 일치합니다.

```json
{
  "structured_case_data": {},
  "evidence_mapped_data": {},
  "session_summary_draft": {},
  "verification_report": {},
  "document_transform_preview": {},
  "confirmed_session_note": {},
  "sanitized_input": {},
  "stub": true
}
```

주요 응답 필드:

- `structured_case_data`: 주호소, 회기 주제, 상담 내용, 상담자 개입, 내담자 반응, 주요 발화, 비언어 메모, reflection 후보, 추후 계획
- `evidence_mapped_data`: 각 항목의 근거 유형과 source reference
- `session_summary_draft`: frontend에서 textarea로 수정 가능한 회기요약 초안
- `verification_report`: 근거 있음, 근거 부족/추론 가능성, 민감정보 후보, 상담사 확인 필요 항목
- `document_transform_preview`: 슈퍼비전/종결 보고서 변환 preview, 부분 입력 필드, 부족 필드
- `sanitized_input`: 입력 정제 결과와 민감정보 후보
- `stub`: deterministic mock/stub output 여부

### 상태 코드

- `200`: 성공
- `422`: FastAPI/Pydantic validation error
- `500`: 서버 오류

### 에러 응답 예시

```json
{
  "detail": "회기요약 생성 중 오류가 발생했습니다: [오류 메시지]"
}
```

## 3. Legacy Alias

```text
POST /api/notes/session-draft
```

이 경로는 예전 local client/Streamlit 호환을 위한 hidden alias입니다. MVP V0의 문서화된 주 API는 `POST /api/notes/generate`입니다.

## 4. Stub 동작

OpenAI API key가 없거나 `USE_STUB=1`이면 deterministic mock/stub output으로 동작합니다. 이 모드는 API key 없이 데모와 smoke test를 실행하기 위한 기본 안전장치입니다.
