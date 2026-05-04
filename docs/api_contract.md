# API 계약서 (Contract)

## 엔드포인트: POST /api/notes/session-draft

### 요청 (Request)

```json
{
  "case_id": "string (필수)",
  "session_no": "number (필수, 양수)",
  "counselor_memo": "string (필수)",
  "transcript": "string (필수, 상담 축어록)",
  "prev_summary": "string (선택사항)"
}
```

**예시:**
```json
{
  "case_id": "CASE001",
  "session_no": 3,
  "counselor_memo": "김지은 대학생, 진로불안. 강점 자기이해 진행 중.",
  "transcript": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 진로가 여전히 불확실해요...",
  "prev_summary": "회기 2: 강점 중심 자기이해 진행. 창의성, 대인관계 능력이 주요 강점."
}
```

### 응답 (Response)

```json
{
  "structured": {
    "basic_info": "string",
    "presenting_problem": "string",
    "goals": "string",
    "session_content": "string",
    "counselor_intervention": "string",
    "client_response": "string",
    "assessment": "string",
    "next_plan": "string"
  },
  "summary": {
    "session_content": "string",
    "counselor_opinion": "string",
    "session_summary": "string",
    "next_counseling_plan": "string"
  },
  "verification": {
    "grounded": [
      {"content": "string", "source": "string"},
      ...
    ],
    "ungrounded": [...],
    "sensitive": [...],
    "needs_human_judgment": [...]
  }
}
```

**예시 응답:**
[`sample_data/session_output_001.json` 참고]

### 상태 코드

- **200**: 성공
- **400**: 잘못된 요청 (필수 필드 누락 등)
- **500**: 서버 오류 (LLM 호출 실패 등)

### 에러 응답

```json
{
  "detail": "회기 요약 생성 중 오류 발생: [오류 메시지]"
}
```
