# Product Runtime Map

## Current product path

```text
Transcript
→ Raw Window Retrieval
→ Grounded Generation
→ Semantic Source Validation
→ Counselor Evidence Review
→ Document conversion/export
```

`ENABLE_RAW_REGION_GROUNDING=false` is the default. When it is false, the existing legacy generation path continues and `grounding` is absent. When it is true, the raw-region nodes below run inside the same LangGraph.

| Feature | Runtime entry | Main files | Data/storage | Tests |
| --- | --- | --- | --- | --- |
| Frontend shell and session draft | `frontend/src/main.tsx` → `App` → `SessionDraftPage` | `frontend/src/App.tsx`, `frontend/src/pages/SessionDraftPage.tsx` | Browser state; temporary draft API where requested | `frontend/scripts/verify-material-workflow.mjs`, browser verification |
| Note generation API | `generateNoteDraft` → `POST /api/notes/generate` | `frontend/src/api/client.ts`, `api/notes/generate.py`, `backend/app/api/routes/notes.py` | Optional persistence only when configured and requested | `backend/test_vercel_wrappers.py`, `backend/smoke_test.py` |
| LangGraph orchestration | `run_note_pipeline` | `backend/app/graph/graph.py`, `backend/app/graph/nodes.py` | Request-local graph state | `backend/test_grounded_generation.py`, `backend/smoke_test.py` |
| Evidence need formulation | `formulate_grounding_needs` | `backend/app/graph/nodes.py`, `backend/app/services/grounded_generation.py`, `backend/app/schemas/grounding.py` | Request-local `EvidenceNeed` objects | `backend/test_grounded_generation.py` |
| Raw transcript storage and windows | `store_transcript_turns`, `index_transcript_windows` | `backend/app/services/transcript_storage.py`, `backend/app/services/transcript_windows.py`, `backend/app/schemas/evidence.py` | `transcript_turns`, `transcript_windows` | `backend/test_transcript_storage.py`, `backend/test_raw_window_pipeline.py` |
| Raw region retrieval | `retrieve_raw_evidence_regions` | `backend/app/graph/nodes.py`, `backend/app/services/raw_evidence_retrieval.py`, `backend/app/services/grounded_generation.py` | `match_transcript_windows` RPC; exact scoped turns rebuild each region | `backend/test_raw_window_pipeline.py`, `backend/test_grounded_generation.py` |
| Grounded generation | `generate_grounded_document` | `backend/app/graph/nodes.py`, `backend/app/services/grounded_generation.py`, `backend/app/schemas/grounding.py` | Request-local source registry and claim citations | `backend/test_grounded_generation.py` |
| Claim-source validation | `validate_claim_sources` | `backend/app/graph/nodes.py`, `backend/app/services/claim_support_validation.py`, `backend/app/services/grounded_generation.py` | Validated `GroundedGenerationResult`; optional source snapshots in `evidence_items` | `backend/test_grounded_generation.py` |
| Counselor evidence review | `buildGroundingReviewItems` → `GroundingEvidenceReview` | `frontend/src/lib/groundingReview.ts`, `frontend/src/components/note/GroundingEvidenceReview.tsx`, `frontend/src/pages/SessionDraftPage.tsx` | Response-local cited sources; edited claims become stale | `frontend/scripts/verify-grounding-review.mjs`, `frontend/scripts/verify-grounding-demo-browser.mjs` |
| Document conversion/export | final document builder → `POST /api/documents/export` | `frontend/src/pages/SessionDraftPage.tsx`, `frontend/src/api/client.ts`, `api/documents/export.py`, `backend/app/api/routes/documents.py`, `backend/app/services/document_export.py` | Exported bytes only; no research dependency | `backend/test_supervision_form.py`, `backend/smoke_test.py`, frontend workflow checks |

The current production feature-flag-on backend chain is:

```text
api/notes/generate.py
→ backend/app/api/routes/notes.py
→ backend/app/graph/graph.py
→ backend/app/graph/nodes.py::formulate_grounding_needs
→ backend/app/services/grounded_generation.py::retrieve_raw_regions_for_needs
→ backend/app/services/raw_evidence_retrieval.py
→ backend/app/services/transcript_storage.py
→ backend/app/services/grounded_generation.py::generate_grounded_claims
→ backend/app/services/claim_support_validation.py
→ backend/app/services/supabase_storage.py (only when persistence is enabled/requested)
```

## Repository classification

| Category | Files or directories | Decision |
| --- | --- | --- |
| PRODUCT_RUNTIME | `api/`, `backend/app/api`, `backend/app/graph`, `backend/app/schemas`, production files in `backend/app/services`, `frontend/src` excluding `fixtures/dev`, production Supabase migrations | Keep in the deployable path. No file in these paths imports `research`. |
| PRODUCT_TESTS | `backend/smoke_test.py`, `backend/test_grounded_generation.py`, `backend/test_raw_window_pipeline.py`, `backend/test_supervision_form.py`, `backend/test_transcript_storage.py`, `backend/test_vercel_wrappers.py`, `frontend/scripts/verify-*.mjs` | Keep beside the product because they protect current runtime behavior. |
| EXPERIMENTAL_RESEARCH | `research/raw_evidence_experiments`, `research/case_retrieval_experiments`, `research/legacy_muspsy_evaluation`, legacy evaluation harnesses in top-level `scripts/`, public synthetic MusPsy fixtures in `sample_data/muspsy_demo` | Keep for reproducibility. They are not imported by the product runtime. |
| GENERATED_ARTIFACTS | `results/debug`, `counselor_demo_ready`, `tmp_ab`, screenshots, evaluation JSON/Markdown under results, ZIPs, logs, caches and builds | Do not track. Local copies may remain ignored. |

## Experimental path audit

| Path | Runtime dependency? | Product test dependency? | Experiment only? | Safe to move? | Safe to delete? |
| --- | --- | --- | --- | --- | --- |
| `evidence_extraction.py` | No | No | Yes: global/scene episode extraction | Yes; moved to research | No; retained for comparison history |
| turn-function labeling and deterministic episode assembly | No | No | Yes | Yes; moved to research | No; retained with tests |
| `query_evidence_selection.py` | No | No | Yes: query-conditioned exact-span selector | Yes; moved to research | No; retained with tests |
| `raw_evidence_pipeline.py` | No | No | Yes: standalone selector pipeline | Yes; moved to research | No; retained with tests |
| evidence episode retrieval | No | No | Yes: `evidence_episodes` plus `match_evidence_episodes` | Yes; code and SQL moved to research | No; retained outside migration chain |
| controlled synthetic evaluation scripts | No | No | Yes | Yes; moved under the matching research package | No; retained for reproducibility |

## Database decision

The release baseline treats `20260901000100_case_schedule_and_transcript_status` and `20260902000100_document_exports` as already applied remotely. The raw-evidence schema is therefore ordered afterward as `20260903000100_raw_evidence_layer` and `20260903000200_transcript_window_retrieval`; these two migrations must remain unapplied until release review. `evidence_episodes` and `match_evidence_episodes` remain research-only.

The final product architecture requires `transcript_turns` and `transcript_windows`. It does not call `evidence_episodes` or `match_evidence_episodes`. Therefore the unapplied production migration chain now excludes the episode table/function; their SQL is retained only in `research/raw_evidence_experiments/supabase`. Nothing was applied to the remote project.

## Development-only evidence demo

`frontend/src/fixtures/dev/groundingDemo.ts` contains synthetic data only. `App` loads its DEV-only page lazily, so the fixture is absent from the production bundle. It is reachable only when both conditions hold:

```text
import.meta.env.DEV
?grounding-demo=1
```

The normal product flow continues to call the generation API and does not load this fixture.

## Historical branches retained

- `codex/hansangsim-supervision-form`: supervision-form implementation history.
- `codex/counselor-ready-integration`: counselor-ready integration checkpoint.
- `codex/raw-evidence-grounding-demo-ready`: raw-evidence grounding and demo-ready checkpoint.

These branches are historical checkpoints and are not deleted or rewritten by repository cleanup.
