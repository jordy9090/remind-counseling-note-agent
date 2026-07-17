# Supabase pgvector Workflow

Project dashboard:
https://supabase.com/dashboard/project/bgjapctiawosgpjcyfuq

Project ref:
`bgjapctiawosgpjcyfuq`

## Current Access Status

This Codex session could run `npx supabase --version`, but Supabase CLI was not
authenticated:

```text
Access token not provided. Supply an access token by running `supabase login`
or setting the SUPABASE_ACCESS_TOKEN environment variable.
```

Remote schema pull, migration push, row counts, seed insertion, and sample
remote retrieval queries are blocked until the local CLI is authenticated or
`SUPABASE_ACCESS_TOKEN` and service credentials are available.

## Non-Destructive Remote Workflow

```bash
npx supabase login
npx supabase link --project-ref bgjapctiawosgpjcyfuq
npx supabase db pull
npx supabase db push
```

Do not run `supabase db reset` against the shared project.

Before applying migrations, review:

- `supabase/migrations/20260717000100_baseline_schema.sql`
- `supabase/migrations/20260717000200_pgvector_hybrid_rag.sql`

The migrations create missing baseline tables, enable pgvector, add source-aware
KB metadata, add `case_memory_chunks`, add full-text search support, and define:

- `match_kb_chunks`
- `match_case_memory_chunks`
- `hybrid_search_kb`

## Seed And Embedding Commands

Run only after migrations are applied:

```bash
python scripts/seed_kb_examples.py
python scripts/embed_kb_chunks.py
python scripts/check_supabase_remote.py
```

Synthetic case-memory demo data is separate and must never be replaced with real
counseling records by default:

```bash
USE_STUB=1 python scripts/seed_synthetic_case_memory.py
```

## Safety Boundary

Real counseling data must not be embedded or stored until auth, RLS, audit
logging, retention policy, consent handling, and export controls are implemented
and reviewed.

