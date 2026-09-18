# Architecture

## Baseline and responsibilities

Current implementation baseline: `4815b4457af2c5ccbccbafe4e53687229988346c`.
The user confirmed that on 2026-09-09 Production runs this SHA on Vercel with
`git / main / READY`, at [remind.ai.kr](https://remind.ai.kr).
Remote environment variables and Supabase migration/RLS state have not been verified.
This document describes only the implementation at this commit.

| Layer | Responsibility |
| --- | --- |
| Frontend | Auth entry, session material editing, response projection for display, evidence review, document transformation/download requests |
| Backend | Auth actor validation, API/Pydantic contracts, graph execution, material extraction/audio transcription/document export, persistence requests |
| AI workflow | Note structuring, summarization, verification, and optional retrieval/grounding; separate supervision form assembly |
| Storage | User-scoped cases, sessions, drafts, confirmed notes, evidence, retrieval data, and export history |
| Research | Experiment/evaluation code not imported by the product; separate from the product runtime and migration chain |

Feature-specific files and APIs are collected in the [Product Runtime Map](product_runtime_map.md);
relationships and persistence conditions are in the [Data Model](data_model.md).

## Frontend

```text
main.tsx → App
             ├─ DEV + ?grounding-demo=1 → lazy GroundingDemoPage
             └─ AuthGate
                  ├─ No auth configuration → connection preparation screen
                  ├─ No session → Landing (public) → 로그인 / 무료로 시작하기
                  │      → email signin · signup (+ confirmation email, resend) · password reset
                  │      → PASSWORD_RECOVERY event → new-password form
                  └─ Existing session → SessionDraftPage (header shows email + 로그아웃)
```

Anonymous sign-in was removed; the API guard also rejects tokens whose user is `is_anonymous`.
OAuth buttons appear only when a provider is enabled remotely (out of scope for the normal path).
The Supabase SDK maintains and refreshes the auth session; Axios sends its access token to the API.

The normal workspace switches screens using `currentScreen` state instead of a URL router.

```text
session_input → summary_draft → document_transform → final_document
      ↕
   case_list (dashboard lookup and schedule updates for an existing case ID)
```

The normal entry screen is `session_input`. Input, edits, and final documents live in React memory;
there is no flow to restore the screen from a URL or persistent storage. The temporary-save button only
displays a message. Note generation uses `persist:false`; supervision generation also makes no save request.
Checklist changes affect local display and are not connected to the recompose/confirm APIs.
The case dashboard separately reads the DB and updates schedules, so not saving notes does not
disable reads/writes across all APIs.

## Backend

```text
Frontend /api
  ├─ Integrated FastAPI app (local/server)
  │    └─ health / notes / cases / materials / audio / documents routers
  └─ Vercel api/ Python functions
       └─ Individual FastAPI wrapper → shared route or service
```

Vercel deploys the Vite static build and individual wrappers. The user-confirmed Production source
is Git main, but the repository's GitHub Actions contain no deployment job.
Detailed deployment policies and environment variables require checking remote settings.

The two backends do not run exactly the same app. Key differences:

- Audio APIs exist only in the integrated FastAPI app. Vercel wrappers have no WhisperX path.
- FastAPI export records export history on a best-effort basis when persistence is enabled;
  Vercel export does not call the same recording function.
- The integrated FastAPI CORS allowlist contains localhost addresses. Connecting a separate Production
  origin requires more than changing `VITE_API_BASE_URL`.
- `vercel.json` rewrites draft-detail and case dashboard/schedule paths to individual functions.

Protected APIs obtain an actor through the shared auth dependency. With `ENABLE_REAL_USER_AUTH=1`,
it validates the Bearer token through Supabase `/auth/v1/user` and passes the user ID and JWT onward.
User DB paths apply RLS using a public key and the validated JWT. Legacy preview tokens and local
bypass are separate paths that must be explicitly enabled. `counselor_name` is not an authorization identifier.

## Note graph

The entry point is `run_note_pipeline`; `backend/app/graph/graph.py` defines the wiring.
There are 16 registered nodes. The five marked * below return empty/no-op state when grounding is OFF.

```text
sanitize_input
→ formulate_evidence_needs *
→ formulate_retrieval_query
→ retrieve_raw_evidence_regions *
→ retrieve_case_memory
→ retrieve_authoritative_kb
→ assemble_generation_grounding *
→ fuse_and_rerank
→ structure_session
→ map_evidence
→ generate_summary
→ generate_grounded_document *
→ validate_claim_sources *
→ verify_output
→ conditional_revision
    ├─ reverify → verify_output (at most one additional pass)
    └─ preview → transform_document_preview → END
```

The default path de-identifies input, structures it, maps source references, generates a summary,
verifies output, and assembles document drafts/previews. OpenAI structured output uses Pydantic contracts.
A deterministic stub is used with `USE_STUB=1` or without an API key.
The Generate API also retries pipeline exceptions with a stub fallback.
A successful response alone therefore does not establish that a real model ran; inspect `stub` and the report fields.

When risky claims are found, `conditional_revision` marks summary items without direct evidence for
review and verifies once more. It does not rewrite the text with an LLM.
`fuse_and_rerank` aggregates retrieval metrics; it does not run a separate reranker model.
Nodes call retrieval functions directly; there is no ToolNode or autonomous tool selection.

### Retrieval and grounding OFF/ON

| Condition | Actual behavior |
| --- | --- |
| `ENABLE_RAG=false` (default) | Skips case/KB retrieval; independent of generation and persistence settings |
| RAG ON, dense OFF | Lightweight search of saved confirmed notes for the same user/case and the template/ethics KB |
| RAG ON, `ENABLE_DENSE_RETRIEVAL=true` | Case-memory vector search and KB dense/hybrid search, with lightweight fallback when needed |
| `ENABLE_HYBRID_RETRIEVAL=true` (code default) | Selects the hybrid RPC for KB search on the dense path; does not enable RAG by itself |
| `ENABLE_RAW_REGION_GROUNDING=false` (default) | The five nodes above are no-ops; the model's `grounding` value is None and is declared to be omitted during serialization |
| Grounding ON | Adds evidence needs, a source registry, grounded claims, and source ID/hierarchy and semantic support validation |

Raw-region retrieval requires more than grounding ON: RAG ON, dense ON, a DB connection, transcript
tables/RPCs, and previously stored and embedded windows. Window candidates are reassembled from scoped
transcript turns; neither the query nor window search text itself is used as final evidence.
Unmet conditions and retrieval failures are recorded in the report; execution may continue with empty raw context.

**Raw transcript turn/window ingestion is not automatically connected to the current product flow.**
Upload, STT, and note persistence do not call the storage/indexing helpers.
Enabling flags or applying migrations alone does not automatically create historical source retrieval data.

With grounding ON, claims are checked for cited IDs and permitted source hierarchy; semantic support is
validated using only the cited sources. Partially supported/unsupported claims and clinical inferences
require counselor review. Stub support checks are limited to source-text containment, distinct from
real-model semantic validation. The frontend displays cited sources in the review UI and marks grounding
for edited items as stale.

## Supervision graph

The separate entry point `run_supervision_report_pipeline` runs these 11 nodes in a fixed order.

```text
load_case_context → normalize_inputs → build_evidence_index
→ generate_section_A → generate_section_B → generate_section_C
→ generate_supervision_questions → evidence_grounding_checker
→ clinical_safety_guard → generate_ai_review_panel → format_supervision_report
```

This graph places session materials and summaries from the request into a form using rules.
`load_case_context` is not a DB lookup. The graph does not directly call an LLM, retrieve case memory/KB,
or perform the note graph's raw-region semantic validation. Its grounding checker checks evidence ID
existence and some missing evidence.

The current frontend sends the latest counselor-edited summary, session input, pseudonym, and transcript
mode. Not all backend fields for additional session history, previous supervision feedback, clinical goals,
and strategies are connected to the UI. Missing information remains marked as requiring input in the form.
The current screen locally assembles session notes and termination documents from the edited summary;
only supervision calls a separate report API.

## Storage and file boundaries

### Currently unsupported scope

At this baseline commit, real-time counseling intervention/monitoring, recording/streaming STT,
payment/booking services, center administration, theory lens/theory KB, and bulk case import are not implemented.
Updating a case's planned session count and next session date is separate from a booking service.
OCR for scanned-image PDFs and HWPX export are also unsupported. This list describes current scope, not a development plan.

### Persistence conditions

`ENABLE_RAG` (retrieval), `ENABLE_PERSISTENCE` (note/report persistence), and
`ENABLE_RAW_REGION_GROUNDING` (additional grounding) are independent conditions.
Note persistence also requires request `persist=true`; report persistence requires top-level `persist=true`.
The confirm API validates an already-saved note before updating its confirmed JSON.

`ENABLE_CASE_MEMORY` controls memory indexing during confirmation; it is not a global switch blocking
reads of existing memory. `SAVE_RAW_INPUT` controls only the session raw field.
The Temporary Draft API and recompose disk cache are separate paths, not blocked by the same flag.

Original document/audio uploads use temporary files during the request and clean them up. Retention of
extracted text, generated results, and drafts is separate from not retaining original files. DOCX is
generated server-side. PDF prefers WeasyPrint, with a ReportLab fallback on ImportError/OSError.
HWPX is unsupported.

See the [Data Model](data_model.md) for entities, FKs, RLS, and migration status.
Code existence alone does not establish remote application or completed operational controls for real use.
