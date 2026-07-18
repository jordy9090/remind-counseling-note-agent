# Deployment Checklist

Remote Supabase integration can be verified from the linked CLI, but deployment
environment configuration still needs a credentialed deployment session.

Deployment access check on 2026-07-18 KST:

- `vercel --version` was not available on PATH.
- A local `.vercel/` project link exists, but `.vercel/*.env*` files were not
  opened because they may contain secrets.
- No preview deployment was created from this session.

Required server-side variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`
- `RUNTIME_ENVIRONMENT=production`
- `REMIND_PREVIEW_API_TOKEN=<preview-only random token>`
- `REMIND_PREVIEW_ACTOR=preview_server_actor`
- `REMIND_ALLOW_LOCAL_BYPASS=0`
- `ENABLE_RAG=1`
- `ENABLE_DENSE_RETRIEVAL=1`
- `ENABLE_HYBRID_RETRIEVAL=1`
- `EMBEDDING_MODEL=text-embedding-3-small`
- `EMBEDDING_DIMENSION=1536`
- `ENABLE_PERSISTENCE=0` for public preview unless token protection and synthetic-only data are verified
- `ENABLE_CASE_MEMORY=0`
- `SAVE_RAW_INPUT=0`
- `EMBEDDING_CACHE_TTL_SECONDS=300`
- `EMBEDDING_CACHE_MAX_ENTRIES=256`

Frontend preview variables:

- `VITE_API_BASE_URL=<backend URL>`
- `VITE_REMIND_PREVIEW_API_TOKEN=<same preview token, preview only>`

Do not expose service-role or OpenAI credentials through `VITE_` variables. The `VITE_REMIND_PREVIEW_API_TOKEN` value is visible in browser code, so it is a temporary preview gate only and must not be treated as production auth.

Remaining steps:

1. Confirm which deployment target serves the FastAPI backend.
2. Install or authenticate the deployment CLI if CLI-based env updates are
   preferred.
3. Add the server-side variables through the deployment provider secret UI/CLI.
4. Deploy a preview environment.
5. Verify `/api/health`.
6. Run one synthetic generation request with `persist=false`.
7. Run one synthetic persisted request only after preview-token protection, RLS,
   and service-role backend access have been confirmed.
