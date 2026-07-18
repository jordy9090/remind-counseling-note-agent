# Supabase Remote Verification

- Project ref: `bgjapctiawosgpjcyfuq`
- Embedding model: `text-embedding-3-small`
- Embedding dimension: `1536`
- Verification elapsed: `122221.514 ms`
- Secrets: not printed or stored in this report.
- Data scope: synthetic/demo data only.

## Commands Run

- `npx supabase migration list --linked`
- `python scripts/seed_kb_examples.py`
- `python scripts/embed_kb_chunks.py`
- `python scripts/seed_synthetic_case_memory.py`
- `python scripts/check_supabase_remote.py --write-report docs/supabase_remote_verification.md`

## Migration Status

```text
{"migrations":[{"local":"20260717000100","remote":"20260717000100","time":"2026-07-17 00:01:00"},{"local":"20260717000200","remote":"20260717000200","time":"2026-07-17 00:02:00"}],"message":"Migrations listed"}
```

## Enabled Extensions

| extname | extversion | schema_name |
| --- | --- | --- |
| pg_trgm | 1.6 | extensions |
| pgcrypto | 1.3 | extensions |
| vector | 0.8.0 | extensions |

## Tables And RLS

| rls_enabled | row_count | table_name |
| --- | --- | --- |
| True | 3 | case_memory_chunks |
| True | 1 | cases |
| True | 0 | counseling_drafts |
| True | 0 | evidence_items |
| True | 1 | generated_notes |
| True | 7 | kb_chunks |
| True | 7 | kb_documents |
| True | 0 | retrieval_logs |
| True | 1 | sessions |
| True | 0 | verification_reports |

## RPC Functions

| arguments | function_name |
| --- | --- |
| query_text text, query_embedding vector, match_count integer, filter_doc_categories text[], filter_document_type text, filter_allowed_uses text[], filter_authority_levels text[] | hybrid_search_kb |
| query_embedding vector, filter_counselor_id text, filter_case_id text, filter_field_types text[], match_count integer | match_case_memory_chunks |
| query_embedding vector, match_count integer, filter_doc_categories text[], filter_document_type text, filter_allowed_uses text[], filter_authority_levels text[] | match_kb_chunks |

## KB Document Counts

| allowed_use | authority_level | count | doc_category | source_org |
| --- | --- | --- | --- | --- |
| verification_warnings_only | public_principle_paraphrase | 1 | counseling_ethics | Korean Counseling Association |
| verification_warning_only | public_guideline_paraphrase | 1 | deidentification_guideline | Personal Information Protection Commission |
| verification_warning_only | internal_demo | 1 | internal_security_policy | Re:mind internal demo |
| verification_warning_only | public_law_paraphrase | 1 | privacy_law | Korea Law Information Center |
| documentation_structure_only | internal_demo | 1 | session_note_template | Re:mind internal demo |
| documentation_structure_only | internal_demo | 1 | supervision_report_template | Re:mind internal demo |
| documentation_structure_only | internal_demo | 1 | termination_report_template | Re:mind internal demo |

## KB Chunk Counts

| allowed_use | chunk_type | count | document_type | embedded_count |
| --- | --- | --- | --- | --- |
| verification_warning_only | deidentification_warning | 1 |  | 1 |
| verification_warnings_only | ethics_warning | 1 |  | 1 |
| verification_warning_only | privacy_warning | 1 |  | 1 |
| verification_warning_only | security_warning | 1 |  | 1 |
| documentation_structure_only | template_fields | 1 | session_note | 1 |
| documentation_structure_only | template_fields | 1 | supervision_report | 1 |
| documentation_structure_only | template_fields | 1 | termination_report | 1 |

## Case Memory Counts

| case_id | counselor_id | count | embedded_count | field_type |
| --- | --- | --- | --- | --- |
| demo-case-001 | demo-counselor | 1 | 1 | client_response |
| demo-case-001 | demo-counselor | 1 | 1 | next_plan |
| demo-case-001 | demo-counselor | 1 | 1 | session_theme |

## Embedding Dimension Checks

| all_1536 | embedded_count | max_dimension | min_dimension | scope |
| --- | --- | --- | --- | --- |
| True | 7 | 1536 | 1536 | kb_chunks |
| True | 3 | 1536 | 1536 | case_memory_chunks |

## Duplicate Checks

| duplicate_groups | scope |
| --- | --- |
| 0 | kb_document_slug |
| 0 | kb_chunk_source_ref |
| 0 | case_memory_source_ref |

## Raw Storage Checks

| sessions_with_raw_input | suspicious_sanitized_sessions |
| --- | --- |
| 0 | 0 |

## Dense Probe

- Query: `회기 요약에서 상담 개입과 내담자 반응을 어떻게 기록해야 하나`
| source_ref | method | score | category | field_type | title | case_id | section |
| --- | --- | --- | --- | --- | --- | --- | --- |
| kb:session-note-template-v1:1 | dense | 0.315881 | session_note_template |  | Re:mind session note template checklist |  | session_note > required_fields |

## Korean Remote Retrieval Queries

### Query A

- Query: `회기 요약에서 상담 개입과 내담자 반응을 어떻게 기록해야 하나`
- Expected: session-note/template chunks
- Latency: `6499.234 ms`
- Expected result in top 5: `True`

| source_ref | method | score | category | field_type | title | case_id | section |
| --- | --- | --- | --- | --- | --- | --- | --- |
| kb:session-note-template-v1:1 | hybrid:dense | 0.016393 | session_note_template |  | Re:mind session note template checklist |  | session_note > required_fields |

### Query B

- Query: `슈퍼비전 보고서에서 상담자가 직접 작성해야 하는 사례개념화와 질문 항목`
- Expected: supervision-template chunks and counselor-review fields
- Latency: `7775.823 ms`
- Expected result in top 5: `True`

| source_ref | method | score | category | field_type | title | case_id | section |
| --- | --- | --- | --- | --- | --- | --- | --- |
| kb:supervision-report-template-v1:1 | hybrid:dense | 0.016393 | supervision_report_template |  | Re:mind supervision report template checklist |  | supervision_report > required_fields |

### Query C

- Query: `상담 기록 저장 전에 이름과 연락처를 어떻게 처리해야 하나`
- Expected: privacy/deidentification/security warning chunks
- Latency: `6979.987 ms`
- Expected result in top 5: `True`

| source_ref | method | score | category | field_type | title | case_id | section |
| --- | --- | --- | --- | --- | --- | --- | --- |
| kb:privacy-law-sensitive-info-demo:1 | hybrid:dense | 0.016393 | privacy_law |  | Personal Information Protection Act sensitive information paraphrase |  | privacy_law > sensitive_information |
| kb:deidentification-guideline-demo:1 | hybrid:dense | 0.016129 | deidentification_guideline |  | Pseudonymized information guideline paraphrase |  | deidentification > pseudonymization > demo_warning |
| kb:internal-security-policy-v1:1 | hybrid:dense | 0.015873 | internal_security_policy |  | Re:mind internal security policy draft |  | security > backend_only_service_role |

### Query D

- Query: `이전 회기에서 반복된 자기비난과 회피 행동`
- Expected: only synthetic chunks from the requested counselor_id and case_id
- Latency: `7451.993 ms`
- Expected result in top 5: `True`

| source_ref | method | score | category | field_type | title | case_id | section |
| --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic_case_memory:demo-case-001:1:3 | case_memory_dense | 0.242278 |  | next_plan |  | demo-case-001 |  |
| synthetic_case_memory:demo-case-001:1:2 | case_memory_dense | 0.230468 |  | client_response |  | demo-case-001 |  |
| synthetic_case_memory:demo-case-001:1:1 | case_memory_dense | 0.22885 |  | session_theme |  | demo-case-001 |  |

### Query E

- Query: `이전 회기에서 반복된 자기비난과 회피 행동`
- Expected: zero results from the original case
- Latency: `7441.477 ms`
- Expected result in top 5: `True`

_No rows._

## Cross-Case Leakage

- Cross-case leakage count: `0`
- Query E used the same semantic case-memory query with `case_id=other-case-999` and returned no `demo-case-001` rows.

## Security Notes

- Direct `anon` and `authenticated` table grants are revoked in the MVP migrations.
- RLS is enabled, but production counselor-to-auth-user policies are still required before real counseling data.
- Retrieval logs store query hashes/length and returned refs, not raw retrieval query text.
- HNSW is intentionally deferred; exact search is sufficient for the small MVP corpus.

## Backend And Frontend Checks

| Command | Result |
| --- | --- |
| `uv sync --link-mode=copy` | Failed on a locked existing `.venv` dist-info directory under OneDrive; no application test failure was produced. |
| `uv run python smoke_test.py` | Passed once, then later hit the same local `.venv` lock while trying to mutate packages. |
| `.\.venv\Scripts\python.exe smoke_test.py` | Passed. |
| `npm install` | Failed with npm internal error `Cannot read properties of null (reading 'matches')`. |
| `pnpm install --frozen-lockfile` | Passed; lockfile already up to date. |
| `npm run build` | Passed; TypeScript and Vite production build completed. |

## Deployment Check

- `vercel --version` was not available on PATH.
- A local `.vercel/` project link exists, but local `.vercel/*.env*` files were not opened because they may contain secrets.
- No preview deployment was created from this session. Required server-side variables and manual deployment steps are listed in `docs/deployment_checklist.md`.
