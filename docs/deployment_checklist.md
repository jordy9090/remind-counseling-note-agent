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
- `ENABLE_RAG=1`
- `ENABLE_DENSE_RETRIEVAL=1`
- `ENABLE_HYBRID_RETRIEVAL=1`
- `EMBEDDING_MODEL=text-embedding-3-small`
- `EMBEDDING_DIMENSION=1536`
- `ENABLE_PERSISTENCE=1`
- `SAVE_RAW_INPUT=0`

Do not expose service-role or OpenAI credentials through `VITE_` variables.

Remaining steps:

1. Confirm which deployment target serves the FastAPI backend.
2. Install or authenticate the deployment CLI if CLI-based env updates are
   preferred.
3. Add the server-side variables through the deployment provider secret UI/CLI.
4. Deploy a preview environment.
5. Verify `/api/health`.
6. Run one synthetic generation request with `persist=false`.
7. Run one synthetic persisted request only after RLS and service-role backend
   access have been confirmed.
