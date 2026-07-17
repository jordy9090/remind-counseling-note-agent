# Re:mind

Re:mind는 심리상담사를 위한 AI 보조 상담 문서화 워크스페이스입니다.

MVP V1의 주 경로는 **React + FastAPI + LangGraph 기반 lightweight retrieval-aware workflow**입니다. 상담사가 상담 이후에 가진 상담사 메모, 축어록/STT 텍스트, 이전 회기 요약을 입력하면 backend가 note generation workflow를 실행하고, frontend가 회기요약 초안과 근거 확인 결과를 카드 형태로 보여줍니다.

## 제품 원칙

Re:mind는 상담을 수행하거나, 상담사를 평가하거나, 임상적 판단을 대체하지 않습니다.

- 입력에 없는 정보는 확정적으로 쓰지 않습니다.
- AI 추론, 근거 부족, 상담사 확인 필요 영역을 분리합니다.
- `reflection`, `case_conceptualization`, `goal_attainment`는 상담사 확인 필요 영역으로 표시합니다.
- 생성된 초안은 상담사 검토 전 최종 기록으로 사용하지 않습니다.
- RAG는 상담 판단 보강이 아니라 `case memory`, `document template`, `privacy/ethics/security guardrail`에만 사용합니다.
- 진단, 임상적 위험도 점수화, 치료 권고, 심리검사 자동 해석은 생성하지 않습니다.
- 현재 구현은 production-ready RAG나 실서비스 상담 기록 저장소가 아닙니다. 실제 상담 데이터는 인증, RLS, 감사 로그, 보관기간 정책 전에는 저장하지 않습니다.

## MVP V1 기능 범위

포함:

1. 회기 자료 입력
2. 입력 정제와 민감정보 후보 탐지
3. Supabase 기반 선택적 저장
4. `case_id` 기반 이전 회기 retrieval
5. 상담 문서 양식 KB retrieval
6. 개인정보/윤리/보안 규칙 retrieval
7. 상담 내용 구조화
8. 근거 매핑
9. 회기요약 초안 생성
10. 검증 리포트 생성
11. 문서 변환 preview
12. 상담사 수정용 회기요약 textarea UI

제외:

- 인증/회원가입
- 파일 업로드
- 음성 업로드 또는 실시간 STT
- pgvector 기반 의미 검색
- 정식 문서 export
- 결제/예약/관리자 기능
- AI 슈퍼비전 또는 자동 사례개념화

## API 계약 요약

Primary API:

```text
GET  /api/health
POST /api/notes/generate
```

`POST /api/notes/generate`는 Pydantic으로 검증된 full `GenerateNoteResponse`를 반환합니다. Frontend는 화면 표시를 위해 필요한 필드를 클라이언트에서 변환합니다.

OpenAI API key가 없거나 `USE_STUB=1`이면 deterministic mock/stub output으로 동작합니다. Supabase 환경변수가 없거나 `ENABLE_RAG=0`, `ENABLE_PERSISTENCE=0`이면 기존처럼 요청 단위 처리만 수행합니다. 따라서 API key와 Supabase credentials 없이도 데모와 smoke test를 실행할 수 있습니다.

## 프로젝트 구조

```text
remind-counseling-note-agent/
├── README.md
├── docs/
│   ├── product_spec.md
│   ├── mvp_scope.md
│   ├── architecture.md
│   ├── schema.md
│   ├── api_contract.md
│   ├── demo_scenario.md
│   ├── security_checklist.md
│   ├── supabase_schema.sql
│   ├── kb_seed_examples.json
│   └── development_plan.md
├── scripts/
│   └── seed_kb_examples.py
├── sample_data/
│   ├── session_input_001.json
│   └── session_output_001.json
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── smoke_test.py
│   └── app/
│       ├── main.py
│       ├── api/routes/
│       │   ├── health.py
│       │   └── notes.py
│       ├── core/
│       │   └── config.py
│       ├── graph/
│       │   ├── graph.py
│       │   └── nodes.py
│       ├── prompts/
│       │   ├── structure_prompt.py
│       │   ├── summary_prompt.py
│       │   └── verification_prompt.py
│       ├── schemas/
│       │   └── note.py
│       └── services/
│           ├── llm.py
│           ├── retrieval.py
│           ├── supabase_store.py
│           └── supabase_storage.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── api/client.ts
        ├── pages/SessionDraftPage.tsx
        └── types/session.ts
```

## 실행 방법

### Backend

```bash
cd backend
uv sync --link-mode=copy
uv run uvicorn app.main:app --reload
```

`--link-mode=copy` avoids hard-link issues that can occur on Windows or cloud-synced folders. If `uv` is not installed, run `pip install uv` first.

API 문서:

```text
http://localhost:8000/docs
```

Stub mode로 실행하려면 `backend/.env`에 다음을 둘 수 있습니다.

```env
USE_STUB=1
```

실제 OpenAI 호출을 사용하려면:

```env
OPENAI_API_KEY=sk-proj-your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
USE_STUB=0
```

Supabase 저장과 lightweight RAG를 켜려면 Supabase SQL editor에서 [docs/supabase_schema.sql](docs/supabase_schema.sql)을 실행한 뒤 backend `.env`에 다음을 설정합니다.

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ENABLE_PERSISTENCE=1
ENABLE_RAG=1
ENABLE_DENSE_RETRIEVAL=0
ENABLE_HYBRID_RETRIEVAL=1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
SAVE_RAW_INPUT=0
```

`POST /api/notes/generate`에서 `persist=true`를 보낸 요청만 저장합니다. `SAVE_RAW_INPUT=0`이 기본값이며, 이 경우 `sessions.raw_input_text`는 저장하지 않고 sanitized input과 metadata만 저장합니다. 실서비스 전에는 인증, Row Level Security, 접근권한, 감사 로그, 보관기간 정책을 먼저 확정해야 합니다.

KB seed 예시는 [docs/kb_seed_examples.json](docs/kb_seed_examples.json)에 있습니다. 유료 검사 매뉴얼, 저작권 있는 상담 자료, 실제 내담자 기록은 seed에 넣지 않습니다. Supabase schema를 만든 뒤 demo KB를 넣으려면 repository root에서 다음을 실행합니다.

```bash
python scripts/seed_kb_examples.py
python scripts/embed_kb_chunks.py
python scripts/check_supabase_remote.py
```

### Supabase pgvector workflow

Shared project ref: `bgjapctiawosgpjcyfuq`

This repo now keeps non-destructive Supabase migrations under
`supabase/migrations`. The remote project is the source of truth, so pull before
push whenever Supabase credentials are available.

```bash
npx supabase login
npx supabase link --project-ref bgjapctiawosgpjcyfuq
npx supabase db pull
npx supabase db push
```

Do not run `supabase db reset` against the shared project. Review pending
migrations before applying them. In this Codex session, Supabase CLI auth was
not available, so remote DB pull/push, row counts, seed insertion, and sample
remote retrieval queries were not executed.

Dense retrieval is still opt-in:

```env
ENABLE_RAG=1
ENABLE_DENSE_RETRIEVAL=1
ENABLE_HYBRID_RETRIEVAL=1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

Synthetic retrieval evaluation does not require Supabase or OpenAI:

```bash
python scripts/evaluate_retrieval.py
```

보안 경계는 [docs/security_checklist.md](docs/security_checklist.md)를 기준으로 확인합니다.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

기본 API 주소는 `http://localhost:8000`입니다. 필요하면 frontend 환경변수로 바꿀 수 있습니다.

```env
VITE_API_BASE_URL=http://localhost:8000
```

`pnpm`이 설치되어 있지 않다면 `npm install`과 `npm run dev`를 사용할 수 있습니다. 빌드 검증은 `pnpm build` 또는 `npm run build`로 실행합니다.

## 검증 명령

Backend smoke test:

```bash
cd backend
uv sync --link-mode=copy
uv run python smoke_test.py
```

Frontend build:

```bash
cd frontend
pnpm build
```

`pnpm`이 없으면:

```bash
npm run build
```

Sample data는 [sample_data/session_input_001.json](sample_data/session_input_001.json)과 [sample_data/session_output_001.json](sample_data/session_output_001.json)을 사용합니다.

## 문서

- [제품 명세](docs/product_spec.md)
- [MVP 범위](docs/mvp_scope.md)
- [아키텍처](docs/architecture.md)
- [스키마](docs/schema.md)
- [API 계약](docs/api_contract.md)
- [보안 체크리스트](docs/security_checklist.md)
