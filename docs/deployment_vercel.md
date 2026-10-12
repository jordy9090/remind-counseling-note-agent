# Vercel Deployment

Vercel deploys the Vite frontend and Python serverless wrappers under `api/`.

For the current deployed commit and its difference from `main`, read the [release handoff](seoyoung_handoff.md).
Production was promoted from the work branch; do not assume `main` is the released source.

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
```

Frontend build variables:

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

Do not put `SUPABASE_SERVICE_ROLE_KEY` or `OPENAI_API_KEY` in `VITE_` variables.

## Optional generation and retrieval

The retrieval flags below illustrate an opt-in configuration, not verified Production values. The
four-entry local supervision corpus does not require enabling historical case retrieval.

```env
OPENAI_API_KEY=sk-proj-your-key
OPENAI_MODEL=gpt-5.4
OPENAI_REASONING_EFFORT=low
OPENAI_TIMEOUT_SECONDS=60
RELATIONAL_INSIGHT_TIMEOUT_SECONDS=60
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

Deployment is a separate authorized release action. Promoting a Preview rebuilds it with Production
environment variables. To verify the same production build before assigning domains, stage it with
`vercel deploy --prod --skip-domain`, check that deployment, then use `vercel promote <deployment-id>`.
Record the exact commit, deployment, checks, and previous healthy rollback target.

```bash
npx vercel login
npx vercel pull --yes --environment production
npx vercel deploy --prod --skip-domain --archive=tgz
# Verify the returned deployment, then promote that exact ID.
npx vercel promote <deployment-id>
```

Run the [deployment checklist](deployment_checklist.md) after deployment.
