# API Contract

The MVP V0-alpha end-to-end demo uses FastAPI as the backend and React/Vite as the frontend.

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

The endpoint runs the existing note generation workflow and returns a compact response for the frontend demo. If `OPENAI_API_KEY` is missing, or if the LLM call fails, the backend falls back to deterministic demo output.

### Request

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
  "transcript": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸."
}
```

Compatibility aliases:

- `transcript_text` is also accepted for `transcript`.
- `previous_session_summary` and `prev_summary` are also accepted for `previous_summary`.
- `session_no` is also accepted for `session_number`.

### Response

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

- `source_type`: `transcript`, `counselor_memo`, `previous_summary`, or `ai_inference`
- `confidence`: `high`, `medium`, or `low`
- `missing_items`: fields that may require additional counselor input or review
- `warnings`: safety and review notices shown to the counselor

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
