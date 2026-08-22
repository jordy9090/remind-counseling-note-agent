# Deployment Checklist

Remote Supabase integration can be verified from the linked CLI, but deployment
environment configuration still needs a credentialed deployment session.

Deployment access check on 2026-08-08 KST for the 2026-08-20 counselor demo:

- A local `.vercel/` project link exists.
- The Vercel CLI account/environment lookup did not complete within 60 seconds,
  so production variables were not read or changed.
- The linked Supabase CLI reached the project but failed while creating the
  temporary login role because the database connection timed out.
- No service-role/API credentials are present in the current process or local
  backend env, so remote persistence was not bypassed or simulated.

Required server-side variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY` (required for query embeddings compatible with the seeded KB)
- `OPENAI_MODEL=gpt-4o-mini`
- `USE_STUB=0`
- `RUNTIME_ENVIRONMENT=production`
- `REMIND_PREVIEW_API_TOKEN=<preview-only random token>`
- `REMIND_PREVIEW_ACTOR=demo-counselor`
- `REMIND_ALLOW_LOCAL_BYPASS=0`
- `ENABLE_RAG=1`
- `ENABLE_DENSE_RETRIEVAL=1`
- `ENABLE_HYBRID_RETRIEVAL=1`
- `EMBEDDING_MODEL=text-embedding-3-small`
- `EMBEDDING_DIMENSION=1536`
- `ENABLE_PERSISTENCE=1`
- `ENABLE_CASE_MEMORY=1`
- `SAVE_RAW_INPUT=0`
- `EMBEDDING_CACHE_TTL_SECONDS=300`
- `EMBEDDING_CACHE_MAX_ENTRIES=256`

Frontend build variables:

- Leave `VITE_API_BASE_URL` unset for the same-origin Vercel API wrappers. Set it
  only when a separately hosted backend URL has been verified with CORS.
- `VITE_REMIND_PREVIEW_API_TOKEN=<same preview token, preview only>`

Do not expose service-role or OpenAI credentials through `VITE_` variables. The `VITE_REMIND_PREVIEW_API_TOKEN` value is visible in browser code, so it is a temporary preview gate only and must not be treated as production auth.

The remote synthetic seed must use the same case/actor scope as the counselor demo:

```text
SYNTHETIC_COUNSELOR_ID=demo-counselor
SYNTHETIC_CASE_ID=CASE-2026-05
```

Remaining steps before the August 14 browser rehearsal:

1. Wake/restore the linked Supabase project if it is paused and verify database
   connectivity from the Supabase dashboard.
2. Apply the three repository migrations and seed/embed only the synthetic KB and
   `CASE-2026-05` case memory.
3. Add the server-only and frontend build variables to the Vercel Preview and
   Production scopes, then redeploy so the `VITE_` token is compiled into the bundle.
4. Confirm that service-role and OpenAI keys are not prefixed with `VITE_`.
5. Run `python scripts/check_supabase_remote.py` and require cross-case leakage and
   duplicate groups to both be zero.
6. Complete the browser rehearsal scenario in this checklist's handoff report.
