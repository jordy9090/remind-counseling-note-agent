# Vercel Deployment

Vercel deploys the Vite frontend and Python serverless wrappers under `api/`.

## Project settings

- Framework preset: Vite
- Install command: `npm --prefix frontend install`
- Build command: `npm --prefix frontend run build`
- Output directory: `frontend/dist`

`vercel.json` includes a rule rewriting `/api/notes/drafts/:draft_id` to a serverless-compatible detail endpoint.

## Serverless API coverage

Paths currently provided by the `api/` wrappers:

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

WhisperX audio endpoints currently have no Vercel wrappers because of their heavy model/runtime
dependencies. Deployments requiring audio transcription must use a separate FastAPI/GPU runtime
and set `VITE_API_BASE_URL` to that origin.

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

Do not put `SUPABASE_SERVICE_ROLE_KEY` or `OPENAI_API_KEY` in `VITE_` variables.

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

The synthetic-data UI demo can run with `USE_STUB=1`. Do not upload identifiable
counseling materials to shared/public deployments.

## Deploy

```bash
npx vercel login
npx vercel pull --yes --environment production
npx vercel deploy --prod --archive=tgz
```

Run the [deployment checklist](deployment_checklist.md) after deployment.
