# MVP Specification

이 문서는 현재 구현의 빠른 진입점입니다. 기능 범위는 [mvp_scope.md](mvp_scope.md),
workflow와 agentic 경계는 [architecture.md](architecture.md), request/response schema는
[api_contract.md](api_contract.md)를 기준으로 합니다.

## Runtime

```text
React + TypeScript
  ↓
FastAPI or Vercel Python functions
  ↓
LangGraph document workflows
  ↓
Optional Supabase retrieval/persistence and OpenAI generation
```

주요 구현 위치:

- `backend/app/graph/graph.py`: 회기 문서 workflow
- `backend/app/graph/supervision_report.py`: 수퍼비전 보고서 workflow
- `backend/app/schemas/note.py`: API schema
- `frontend/src/pages/SessionDraftPage.tsx`: 상담사 workspace
- `supabase/migrations/`: pgvector, user ownership, RLS migration

## Validation

```bash
cd backend
uv sync --link-mode=copy
uv run python smoke_test.py
uv run python test_vercel_wrappers.py
uv run python test_supervision_form.py

cd ../frontend
pnpm install --frozen-lockfile
pnpm verify:material-workflow
pnpm verify:audio-transcript-workflow
pnpm build
```

PDF regression은 WeasyPrint system dependencies와 한국어 font가 설치된 환경에서 실행합니다.
GitHub Actions가 backend smoke, serverless wrapper, PDF/supervision, frontend build를 검증합니다.
