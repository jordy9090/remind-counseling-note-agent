# Supabase Remote Preflight

Date: 2026-07-18 KST

## Project

- Linked project ref: `bgjapctiawosgpjcyfuq`
- Project name: `ReMind`
- Status: `ACTIVE_HEALTHY`
- Region: `ap-south-1`
- Postgres: `17.6`
- CLI: `supabase 2.109.1`

## Authentication

- Supabase CLI access token: available through the local CLI profile.
- `SUPABASE_ACCESS_TOKEN`: not present in the shell environment.
- `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_SERVICE_KEY`: not present in the shell environment.
- `OPENAI_API_KEY`: present only in `backend/.env`; the value was not printed.

## Remote Migration History

`npx supabase migration list --linked` reported both local migrations as pending
and no matching remote versions:

- Local pending: `20260717000100`
- Local pending: `20260717000200`

No migration repair was run.

## Enabled Extensions

- `pgcrypto` in `extensions`
- `vector`: not enabled before migration
- `pg_trgm`: not enabled before migration

## Detected Tables

| Table | Exists | RLS | Rows |
| --- | ---: | ---: | ---: |
| `cases` | no | no | n/a |
| `sessions` | no | no | n/a |
| `generated_notes` | no | no | n/a |
| `evidence_items` | no | no | n/a |
| `verification_reports` | no | no | n/a |
| `counseling_drafts` | yes | yes | 0 |
| `kb_documents` | no | no | n/a |
| `kb_chunks` | no | no | n/a |
| `case_memory_chunks` | no | no | n/a |
| `retrieval_logs` | no | no | n/a |

## Existing `counseling_drafts` Contract

Remote columns:

- `draft_id text primary key`
- `case_id text not null`
- `session_number integer not null default 0`
- `saved_at timestamptz not null default now()`
- `data jsonb not null`
- `created_at timestamptz not null default now()`

Remote indexes:

- `counseling_drafts_pkey`
- `counseling_drafts_case_id_idx`
- `counseling_drafts_saved_at_idx`

Remote policies:

- none detected

RLS is enabled, so direct anon/authenticated client access is denied unless a
future policy is added.

## Existing RPCs

No existing public RPCs were detected for:

- `match_kb_chunks`
- `match_case_memory_chunks`
- `hybrid_search_kb`

## KB Counts

`kb_documents` and `kb_chunks` do not exist yet, so category/authority/source
counts are not available before migration.

## Schema Differences And Conflicts

- The remote already has `counseling_drafts` in the app-compatible shape
  (`draft_id`, `case_id`, `session_number`, `saved_at`, `data`).
- The pending local baseline originally assumed a different drafts shape. The
  pending migration was corrected before remote application so new environments
  and the remote app contract use the same table shape.
- No existing remote data rows were found in `counseling_drafts`.
- No remote RAG tables or RPCs existed before migration.

## Planned Non-Destructive Changes

- Create missing RAG/storage tables with `create table if not exists`.
- Preserve existing `counseling_drafts`.
- Add pgvector and pg_trgm extensions if absent.
- Add nullable/source-aware KB metadata columns with `add column if not exists`.
- Add `case_memory_chunks` and privacy-preserving `retrieval_logs`.
- Add exact vector/metadata/text indexes; no HNSW index for the small MVP corpus.
- Create or replace retrieval RPCs.
- Enable RLS and revoke direct anon/authenticated table access.

No destructive SQL, table reset, data deletion, or migration-history repair is
planned.

