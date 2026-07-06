# API Contract

The MVP V1 end-to-end demo uses FastAPI as the backend, React/Vite as the frontend, and optional Supabase-backed retrieval.

## Health Check

```text
GET /api/health
```

Response:

```json
{
  "status": "ok"
}
```

## Generate Note Draft

```text
POST /api/notes/generate
```

The endpoint runs the retrieval-aware LangGraph note generation workflow and returns the full Pydantic-validated `GenerateNoteResponse`. If `OPENAI_API_KEY` is missing, or if the LLM call fails, the backend falls back to deterministic demo output. If Supabase or RAG settings are missing, retrieval and persistence are skipped while the response shape remains stable. The React frontend maps this full response into its screen-specific display state.

### Request

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
  "transcript": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸.",
  "target_document_type": "session_note",
  "persist": false
}
```

Accepted input aliases:

- `transcript_text` is also accepted for `transcript`.
- `previous_session_summary` and `prev_summary` are also accepted for `previous_summary`.
- `session_no` is also accepted for `session_number`.
- `document_type` is also accepted for `target_document_type`.
- `persist=true` stores the generated note only when `ENABLE_PERSISTENCE=1` and Supabase credentials are configured.
- `SAVE_RAW_INPUT=0` is the default; raw counselor memo/transcript payloads are not stored unless `SAVE_RAW_INPUT=1`.

### Frontend Display Projection

The full API response includes `sanitized_input`, `retrieved_case_context`, `retrieved_template_context`, `retrieved_privacy_context`, `retrieval_report`, `structured_case_data`, `evidence_mapped_data`, `session_summary_draft`, `verification_report`, `document_transform_preview`, `confirmed_session_note`, `persistence_report`, and `stub`. The frontend derives the following compact display fields from that full response:

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_summary": "이번 회기에서는 취업 준비 과정에서 나타나는 진로 불안과 자기비난 사고를 다루었다.",
  "main_issue": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
  "counselor_intervention": "상담자는 내담자의 표현을 구체화하고 불안과 자기비난 사고를 탐색하도록 질문함.",
  "client_response": "내담자는 진로 불확실성과 관련된 불안을 언어화함.",
  "next_plan": "다음 회기에는 자동사고 기록지를 함께 검토함.",
  "evidence_check": [
    {
      "claim": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
      "source_type": "transcript",
      "source_excerpt": "C: 지난 회기 이후 어떻게 지내셨나요? Cl: 여전히 진로가 불확실해서 불안해요.",
      "confidence": "high"
    }
  ],
  "missing_items": ["reflection", "case_conceptualization", "goal_attainment"],
  "warnings": ["AI 초안은 상담사의 검토 전 최종 회기 기록으로 사용되지 않습니다."]
}
```

Field notes:

- `source_type`: `transcript`, `counselor_memo`, `previous_summary`, `retrieved_context`, `template_context`, `privacy_context`, or `ai_inference`
- `confidence`: `high`, `medium`, or `low`
- `missing_items`: fields that may require additional counselor input or review
- `warnings`: safety and review notices shown to the counselor

## Recompose Summary Draft

```text
POST /api/notes/recompose
```

When the counselor changes the "요약에 포함할 항목" checklist, the frontend calls this endpoint instead of only hiding sections locally. The backend regenerates a checklist-specific AI draft and caches it by normalized `session_input`, `session_topic`, and `visible_section_ids`, so repeated clicks with the same settings reuse the existing generated draft instead of spending more LLM tokens.

### Request

```json
{
  "session_input": {
    "case_id": "CASE001",
    "session_number": 3,
    "session_date": "2026-05-17",
    "counselor_name": "박상담사",
    "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
    "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
    "previous_session_summary": ""
  },
  "session_topic": "진로 불안과 자기비난 사고 점검",
  "visible_section_ids": ["main_issue", "session_theme", "session_content"]
}
```

### Response

```json
{
  "result": {},
  "visible_section_ids": ["main_issue", "session_theme", "session_content"],
  "cache_key": "sha256-cache-key",
  "cache_hit": false
}
```

`result` is the same full `GenerateNoteResponse` shape returned by `POST /api/notes/generate`.

## Temporary Draft Save

```text
POST /api/notes/drafts
GET  /api/notes/drafts/{draft_id}
GET  /api/notes/drafts?case_id=CASE001
```

The temporary draft endpoint stores the counselor's current workspace state before final confirmation. It preserves the current screen, raw input form, selected checklist items, editable summary sections, and generated draft response when available.

### Save Request

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "박상담사",
  "screen": "summary_draft",
  "form": {},
  "session_topic": "진로 불안과 자기비난 사고 점검",
  "visible_section_ids": ["main_issue", "session_theme", "session_content"],
  "draft_sections": [],
  "result": null,
  "final_document_type": "session_note"
}
```

If `draft_id` is included, the backend updates that temporary draft. If it is omitted, the backend creates a new temporary draft.

### Save Response

```json
{
  "draft_id": "draft_1234",
  "case_id": "CASE001",
  "session_number": 3,
  "saved_at": "2026-06-19T03:40:00+00:00",
  "message": "임시저장되었습니다."
}
```

## Local Run

Backend:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
pnpm dev
```

If `pnpm` is not available in the local environment, the same Vite scripts can be run with npm:

```bash
npm run dev
```
