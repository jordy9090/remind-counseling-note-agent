# Vercel Deployment

Vercel은 Vite frontend와 `api/` 아래의 Python serverless wrappers를 배포합니다.

## Project settings

- Framework preset: Vite
- Install command: `npm --prefix frontend install`
- Build command: `npm --prefix frontend run build`
- Output directory: `frontend/dist`

`vercel.json`에는 `/api/notes/drafts/:draft_id`를 serverless-compatible detail endpoint로
rewrite하는 규칙이 있습니다.

## Serverless API coverage

현재 `api/` wrappers가 제공하는 경로:

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
GET  /api/documents/capabilities
POST /api/documents/export
```

WhisperX audio endpoints는 무거운 model/runtime dependency 때문에 현재 Vercel wrapper가
없습니다. Audio transcription이 필요한 배포는 별도 FastAPI/GPU runtime을 사용하고
`VITE_API_BASE_URL`을 그 origin으로 설정해야 합니다.

## Required production authentication

Server variables:

```env
RUNTIME_ENVIRONMENT=production
ENABLE_REAL_USER_AUTH=1
ALLOW_LEGACY_PREVIEW_TOKEN=0
REMIND_ALLOW_LOCAL_BYPASS=0

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SAVE_RAW_INPUT=0
```

Frontend build variables:

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

`SUPABASE_SERVICE_ROLE_KEY`와 `OPENAI_API_KEY`를 `VITE_` 변수에 넣지 않습니다.

## Optional generation and retrieval

```env
OPENAI_API_KEY=sk-proj-your-key
OPENAI_MODEL=gpt-4o-mini
USE_STUB=0

ENABLE_PERSISTENCE=1
ENABLE_RAG=1
ENABLE_CASE_MEMORY=1
ENABLE_DENSE_RETRIEVAL=1
ENABLE_HYBRID_RETRIEVAL=1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

합성 데이터 UI demo는 `USE_STUB=1`로 실행할 수 있습니다. Shared/public deployment에는
식별 가능한 상담자료를 업로드하지 않습니다.

## Deploy

```bash
npx vercel login
npx vercel pull --yes --environment production
npx vercel deploy --prod --archive=tgz
```

배포 후 [deployment checklist](deployment_checklist.md)를 실행합니다.
