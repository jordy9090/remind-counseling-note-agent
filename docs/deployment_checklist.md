# Deployment Checklist

## Before deploy

- [ ] GitHub Actions backend, PDF/supervision, wrappers, frontend jobs pass.
- [ ] Supabase migrations are reviewed and applied in order.
- [ ] Two test users cannot read or mutate each other's cases, sessions, notes, drafts, evidence,
      case memory, or retrieval logs.
- [ ] `ENABLE_REAL_USER_AUTH=1` in production.
- [ ] `ALLOW_LEGACY_PREVIEW_TOKEN=0` and `REMIND_ALLOW_LOCAL_BYPASS=0` in production.
- [ ] Browser environment contains only Supabase URL and publishable key.
- [ ] Service-role and OpenAI keys exist only in server environment variables.
- [ ] `SAVE_RAW_INPUT=0` and `ENABLE_CASE_MEMORY=0` remain set until the corresponding data policy
      is approved.
- [ ] The deployment uses synthetic counseling material for rehearsal.

## Required server variables

```text
RUNTIME_ENVIRONMENT=production
ENABLE_REAL_USER_AUTH=1
ALLOW_LEGACY_PREVIEW_TOKEN=0
REMIND_ALLOW_LOCAL_BYPASS=0
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
SUPABASE_SERVICE_ROLE_KEY
SAVE_RAW_INPUT=0
```

Generation and retrieval variables are optional and must match the selected runtime:

```text
OPENAI_API_KEY
OPENAI_MODEL
USE_STUB
ENABLE_PERSISTENCE
ENABLE_RAG
ENABLE_CASE_MEMORY
ENABLE_DENSE_RETRIEVAL
ENABLE_HYBRID_RETRIEVAL
EMBEDDING_MODEL
EMBEDDING_DIMENSION
```

## Required frontend variables

```text
VITE_SUPABASE_URL
VITE_SUPABASE_PUBLISHABLE_KEY
```

Leave `VITE_API_BASE_URL` unset for same-origin Vercel wrappers. Set it only for a separately
deployed FastAPI origin with verified CORS and authentication.

## Post-deploy checks

1. Logged-out requests to protected counseling endpoints return 401.
2. Login, refresh, logout, expired-token handling, and OAuth redirect work.
3. A user can create, list, load, update, and confirm only their own synthetic draft.
4. Note generation, recompose, supervision report, material extraction, and DOCX export work.
5. PDF download is enabled only when `/api/documents/capabilities` reports it available.
6. Oversized, mismatched, and malicious archive uploads receive the expected error.
7. Browser bundle and network logs contain no service-role or OpenAI key.
8. Server logs contain no raw memo, transcript, access token, or uploaded file contents.
9. Cross-user retrieval returns zero rows and no cross-case evidence appears in generated output.
10. Shared demo copy clearly states that only synthetic data may be uploaded.

## Production-data gate

Do not accept real counseling data until audit logging, retention/deletion, consent, incident response,
vendor/model data processing, backup/export, and access-review procedures are documented and tested.
