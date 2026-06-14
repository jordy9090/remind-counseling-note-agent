# MVP V0 스펙

이 문서는 현재 구현된 MVP V0 기준의 스펙입니다.

## 1. 주 경로

```text
React Frontend
  ↓
FastAPI Backend
  ↓
LangGraph 6-agent Workflow
  ↓
Pydantic validated JSON
```

## 2. Backend

Primary API:

```text
GET  /api/health
POST /api/notes/generate
```

Workflow:

```text
sanitize_input
  ↓
structure_session
  ↓
map_evidence
  ↓
generate_summary
  ↓
verify_output
  ↓
transform_document_preview
```

Schema 기준:

```text
backend/app/schemas/note.py
```

API key 처리:

- `OPENAI_API_KEY`가 있고 `USE_STUB=0`이면 OpenAI API 사용
- `OPENAI_API_KEY`가 없거나 `USE_STUB=1`이면 deterministic stub output 사용

## 3. Frontend

주요 화면:

```text
frontend/src/pages/SessionDraftPage.tsx
```

구현된 UI:

- 회기 자료 입력
- 처리 단계 표시
- 구조화 결과 탭
- 회기요약 초안 textarea 편집
- 검증 리포트 탭
- 문서 변환 Preview 탭
- Raw JSON 탭

## 4. Sample data

```text
sample_data/session_input_001.json
sample_data/session_output_001.json
```

두 파일은 현재 `SessionInput`과 `/api/notes/generate`의 full API response에 맞춰져 있어야 합니다.

## 5. 제외 항목

- DB 저장
- 인증
- 파일 업로드
- 음성 업로드
- 실시간 STT
- Vector DB/RAG
- AI 슈퍼비전
- 자동 사례개념화
- 정식 문서 export

## 6. 검증

Backend:

```bash
cd backend
uv run python smoke_test.py
```

Frontend:

```bash
cd frontend
pnpm build
```

`pnpm`이 없는 환경에서는:

```bash
npm run build
```
