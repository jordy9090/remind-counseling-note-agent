# Re:mind

Re:mind는 수련상담사가 상담 후 자료를 정리하고, 다회기 근거를 확인하며, 회기 기록과
수퍼비전 보고서 같은 공식 문서를 준비하는 AI 보조 workspace입니다.

현재 제품은 React + FastAPI/Vercel Python functions + LangGraph + optional Supabase로
구성됩니다. 상담사 메모, 축어록/STT, 이전 회기 기록을 구조화하고 source reference가
연결된 초안을 만든 뒤 상담사가 수정·확정하고 DOCX/PDF로 내보낼 수 있습니다.

## Product boundary

- 입력에 없는 정보를 확정적으로 쓰지 않습니다.
- `direct`, `ai_organized`, `clinical_review`, `missing` 상태를 구분합니다.
- 사례개념화, 임상 가설, 목표·전략의 최종 판단은 상담사가 수행합니다.
- 생성 초안은 상담사 검토 전 최종 기록으로 사용하지 않습니다.
- 진단, 위험 점수화, 치료 권고, 심리검사 자동 해석, 상담사 평가는 제공하지 않습니다.
- case memory와 KB는 문서화 근거, 양식, 개인정보·윤리 경고 범위에서 사용합니다.

Supabase authentication과 user-scoped RLS 경로가 구현되어 있어도 실제 상담자료 운영에
필요한 감사 로그, 보관·삭제 정책, 동의 절차, 운영 보안 검토는 남아 있습니다. 공유 데모에는
합성 데이터만 사용하세요.

## Implemented workflow

### Note generation

```text
sanitize_input
  → formulate_retrieval_query
  → retrieve_case_memory
  → retrieve_authoritative_kb
  → finalize_retrieval_report
  → structure_session
  → map_evidence
  → generate_summary
  → verify_output
  → conditional_revision
       ├─ reverify → verify_output
       └─ preview  → transform_document_preview
```

이것은 11-node LangGraph stateful workflow입니다. Retrieval service는 graph node에서 직접
호출됩니다. LLM function calling, `ToolNode`, input-dependent retrieval routing, reranker model은
현재 구현되어 있지 않습니다. 자세한 경계는 [architecture](docs/architecture.md)에 있습니다.

### Current capabilities

- PDF 텍스트 레이어, DOCX, TXT 자료 추출
- 선택적 WhisperX transcription과 speaker diarization
- 동일 사용자·사례 범위의 이전 확정 기록 retrieval
- 문서 양식과 개인정보·윤리 KB retrieval
- 선택적 pgvector dense/hybrid retrieval
- 회기요약 생성, 근거 매핑, verification, conditional revision
- 상담사 편집, recompose, confirm, temporary draft persistence
- 한국상담심리학회 개인상담 사례 수퍼비전 보고서 A-1~C-2 초안
- 회기 기록·수퍼비전 보고서·종결 보고서 DOCX export
- 지원 runtime의 PDF export
- Supabase email/password/OAuth frontend auth와 access-token 검증

현재 제외 범위는 OCR, 실시간 STT, HWPX template export, 결제·예약·관리자 기능,
자율형 AI 수퍼바이저입니다. 전체 범위와 알려진 공백은 [MVP scope](docs/mvp_scope.md)를
참조하세요.

## API

```text
GET  /api/health
POST /api/notes/generate
POST /api/notes/confirm
POST /api/notes/recompose
POST /api/notes/supervision-report
POST /api/notes/drafts
GET  /api/notes/drafts
GET  /api/notes/drafts/{draft_id}
POST /api/materials/documents/extract
GET  /api/audio/capabilities
POST /api/audio/transcribe
GET  /api/documents/capabilities
POST /api/documents/export
```

Audio endpoints are available on the FastAPI runtime. The current Vercel serverless wrapper set does
not include WhisperX; see [Vercel deployment](docs/deployment_vercel.md).

`POST /api/notes/generate`는 Pydantic으로 검증된 `GenerateNoteResponse`를 반환합니다.
`USE_STUB=1`에서는 OpenAI key 없이 결정론적 test output을 생성합니다.

문서 업로드는 원본을 영구 저장하지 않고 임시 파일에서 텍스트를 추출한 뒤 정리합니다.
스캔 이미지 PDF OCR은 지원하지 않습니다. 음성 원본도 현재 backend/Supabase에 영구
저장하지 않습니다.

## Repository layout

```text
.
├── api/                         # Vercel Python wrappers
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routes and auth
│   │   ├── graph/               # note and supervision LangGraph workflows
│   │   ├── schemas/             # Pydantic contracts
│   │   └── services/            # retrieval, persistence, export, STT
│   ├── smoke_test.py
│   ├── test_supervision_form.py
│   └── test_vercel_wrappers.py
├── frontend/
│   ├── scripts/                 # static workflow verifiers
│   └── src/                     # React counselor workspace
├── supabase/migrations/         # schema, pgvector, user ownership, RLS
├── docs/
└── .github/workflows/
```

## Local development

### Backend

```bash
cd backend
uv sync --link-mode=copy
uv run uvicorn app.main:app --reload
```

합성 데이터로 local bypass를 사용할 때 `backend/.env`:

```env
USE_STUB=1
RUNTIME_ENVIRONMENT=development
REMIND_ALLOW_LOCAL_BYPASS=1
ENABLE_PERSISTENCE=0
ENABLE_RAG=0
ENABLE_CASE_MEMORY=0
SAVE_RAW_INPUT=0
```

실제 Supabase user authentication 경로의 핵심 설정:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ENABLE_REAL_USER_AUTH=1
ALLOW_LEGACY_PREVIEW_TOKEN=0
REMIND_ALLOW_LOCAL_BYPASS=0
SAVE_RAW_INPUT=0
```

Browser에는 publishable key만 제공하고 service-role key는 backend 환경에만 둡니다.

### Frontend

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

`VITE_API_BASE_URL`을 생략하면 same-origin `/api`를 사용합니다.

## Optional retrieval

Supabase migration은 `supabase/migrations`에서 관리합니다. 공유 project에 적용하기 전에
pending migration과 RLS policy를 검토하세요. `supabase db reset`을 공유 project에 실행하지
마세요.

```env
ENABLE_PERSISTENCE=1
ENABLE_RAG=1
ENABLE_CASE_MEMORY=1
ENABLE_DENSE_RETRIEVAL=1
ENABLE_HYBRID_RETRIEVAL=1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

`ENABLE_CASE_MEMORY=0`과 `SAVE_RAW_INPUT=0`이 안전한 기본값입니다.

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

`test_supervision_form.py`의 PDF regression은 WeasyPrint system dependencies와 한국어 font가
필요합니다. GitHub Actions가 backend smoke, serverless wrappers, PDF/supervision, frontend
build를 별도 job으로 검증합니다.

## Product and security docs

- [Product spec](docs/product_spec.md)
- [MVP scope](docs/mvp_scope.md)
- [Architecture](docs/architecture.md)
- [API contract](docs/api_contract.md)
- [Security checklist](docs/security_checklist.md)
- [Development plan](docs/development_plan.md)
