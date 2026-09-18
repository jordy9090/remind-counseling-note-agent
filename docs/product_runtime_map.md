# Product Runtime Map

Baseline commit: `4815b4457af2c5ccbccbafe4e53687229988346c`.
The connections below reflect this commit, without future design.
Production Git main / the same SHA / READY were confirmed by the user on 2026-09-09.
Remote flags and Supabase migration application remain separately unverified.

## How to read this map

**An API's existence does not mean the UI actually calls it.**
“Connected” in the table describes code connections, not proof of successful remote operation.

- FE paths are relative to `frontend/src/`. Normal entry is `main.tsx → App → AuthGate → SessionDraftPage`.
- BE route/graph/service paths are relative to `backend/app/`. Vercel wrappers are in root `api/`.
- Protected APIs require an authenticated actor. The real-user path uses `ENABLE_REAL_USER_AUTH=1`,
  a Supabase URL/public key, and a valid Bearer token.
- `P`: `ENABLE_PERSISTENCE=1` and an actor DB connection. Note/report saves also require request `persist=true`.
- `R`: `ENABLE_RAG=1` and an actor DB connection. Dense also requires `ENABLE_DENSE_RETRIEVAL=1`.
- `G`: `ENABLE_RAW_REGION_GROUNDING=1`. Raw retrieval requires R+dense and a pre-existing transcript index.
- T1–T8 below refer to commands in the final verification table. “No test” means no dedicated check directly protecting that connection was identified.

## Feature paths

| User action | Frontend | API | Backend/service | Storage | Test | Current UI connection | Required feature flag / condition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Start from Landing | `components/AuthGate.tsx` → `pages/LandingPage.tsx`, `lib/supabase.ts` | Supabase Auth SDK email signup / signin / password reset / signout | Supabase Auth; Re:mind API guard validates Bearer tokens and rejects anonymous users | Auth user/session; SDK persists and refreshes the session | `pnpm verify:auth-flow` (static wiring), backend `test_auth_guard.py` (token guard); real signup/confirmation E2E is manual | Connected. Anonymous entry removed | FE URL/public key + Site URL/Redirect URLs including the app origin + email confirmation enabled |
| Home dashboard / client list / document archive | `pages/HomeDashboardPage.tsx`, `pages/ClientListPage.tsx`, `components/documents/DocumentArchivePage.tsx`, shell `components/app-shell/AppSidebar.tsx`, `lib/caseList.ts` | GET `/api/cases` | `api/routes/cases.py::get_case_list` → `services/supabase_storage.py::list_cases`; wrapper `api/cases/list.py` (rewrite `/api/cases` → `/api/cases/list`) | Reads cases (incl. profile columns, with a base-column fallback when migration 20260918000100 is absent)/sessions/generated_notes/document_exports/counseling_drafts with the user JWT + `user_id` filter; per-case counts + `recent_documents` | T4 (`test_case_list.py`), T2 (wrapper), `pnpm verify:case-list` | Connected. Loaded on workspace entry and whenever home/list/archive/detail opens; status·gender·age filters and search are client-side. Home schedule table is reduced to each case's next scheduled date | Auth+DB. Not gated by R/P/G |
| Create a client / edit profile | `components/clients/ClientFormModal.tsx` (from home, list, picker, detail) | POST `/api/cases`, PATCH `/api/cases/{case_id}/profile` | `api/routes/cases.py::post_case / patch_case_profile` → `services/supabase_storage.py::create_case / update_case_profile`; wrappers `api/cases/list.py` (POST), `api/cases/profile.py` (rewrite `/api/cases/:case_id/profile`) | Inserts/updates cases with `user_id` = actor and profile columns (`client_age`, `client_gender`, `client_occupation`, `marital_status`, `family_composition`, `client_phone`, `client_email`, `client_notes`) | T4 (`test_case_list.py`: create, update, 404 for other users, 409 duplicate, 422 validation, wrapper) | Connected. Requires migration `20260918000100_case_client_profile.sql` on the target project; otherwise the API answers 503 with a migration hint | Auth+DB |
| Open a client profile / restore its records / update schedule | client_detail in `pages/SessionDraftPage.tsx` → `components/case-dashboard/CaseDashboardPanel.tsx` | GET `/api/cases/{case_id}/dashboard`, GET `/api/notes/drafts?case_id=`, PATCH `/api/cases/{case_id}/schedule`; record/draft restore reuses GET `/api/notes/records/{id}` and `/api/notes/drafts/{id}` | `api/routes/cases.py` → `services/supabase_storage.py`; wrapper `api/cases/dashboard.py` | Reads cases/sessions/generated_notes/document_exports; drafts by case; updates cases schedule. `presenting_problem` comes from the latest session note | T4; `pnpm verify:case-list` (record grouping) | Connected. Profile card, month calendar (session dates + next scheduled date), 상담 회기 / 생성된 문서 tabs; session row → note/temporary-draft open; "새 회기 기록" pre-fills case ID/alias/next session number | Auth+DB. Not gated by R/P/G |
| Record a new session (modal) | `components/session-input/SessionRecordModal.tsx`, `components/clients/ClientPickerModal.tsx`, `components/session-input/GeneratingOverlay.tsx` | Same generate/extract/transcribe APIs as before | Unchanged backend | Uploaded documents/audio are extracted/transcribed and auto-applied to `transcript_text` (file row opens the preview/apply modal to change target); checklist selection optionally persists in `localStorage` | `pnpm verify:case-list` (wiring), existing T1/T6 for extract/transcribe | Connected. Session time is display-only (no backend field) | Auth; generation flags as before |
| Enter/extract session materials | `pages/SessionDraftPage.tsx`, `lib/materialWorkflow.ts` | No API for direct input; POST `/api/materials/documents/extract` | `api/routes/materials.py` → extraction/upload validation; same-named Vercel wrapper | Direct input/extraction results in screen state; original uploads use temporary files then cleanup | T1, T2, T6 | Connected. Extracted content must be applied to input before generation uses it | Auth; no R/P/G required |
| Apply audio as a transcript | `components/audio/AudioTranscriptEditor.tsx`, `lib/audioTranscriptWorkflow.ts` | GET `/api/audio/capabilities`, POST `/api/audio/transcribe` | `api/routes/audio.py` → `services/audio_transcription.py` | Temporary audio file; response corrected/applied in the UI. No turn/window DB ingestion | T1, T6 | UI connected. No Vercel wrapper | Separate FastAPI; `AUDIO_TRANSCRIPTION_STUB=1` or real WhisperX enabled with dependencies |
| Generate a summary | `pages/SessionDraftPage.tsx` → `api/client.ts` | POST `/api/notes/generate` | `api/routes/notes.py` → `graph/graph.py::run_note_pipeline`; wrapper `api/notes/generate.py` | Response only by default. P+request saves case/session/note/evidence/verification | T1, T2; T5 for G | Connected. Current request is `persist:false` | Model key or stub. R/P/G are independent options |
| Counselor edits draft / changes display | `pages/SessionDraftPage.tsx`, `lib/groundingReview.ts`, `lib/supervisionDraft.ts` | No API for edits/checklist itself | No BE call at that point | React state; grounding marked stale; latest edits used in supervision/export requests | T7 | Connected. Checklist changes display only | No separate flag |
| Checklist-based regeneration API | Recompose function in `api/client.ts` | POST `/api/notes/recompose` | `api/routes/notes.py` → `services/recompose_cache.py` → note graph; Vercel wrapper | Local result JSON cache with actor-scoped keys | T1, T2 | **Disconnected**. Screen checklist does not call it | Auth; optional R/G. Cache independent of P |
| Counselor confirmation | Confirm function in `api/client.ts` | POST `/api/notes/confirm` | `api/routes/notes.py` → `services/supabase_storage.py::confirm_generated_note`; Vercel wrapper | Updates confirmed_json/status on existing generated_notes; optional case memory | T1, T2 (mock) | **Disconnected** | P+existing owned note. Memory additionally requires `create_case_memory` and `ENABLE_CASE_MEMORY=1` |
| Temporary save/read APIs | Screen button only displays guidance; save function exists in `api/client.ts` | POST/GET `/api/notes/drafts`, GET `/api/notes/drafts/{draft_id}` | `services/draft_store.py` → `supabase_store.py`; drafts/draft wrappers | counseling_drafts or temporary disk JSON per actor | T1, T2 | **Disconnected**. No current screen recovery after refresh | Auth+storage path. Independent of P/`SAVE_RAW_INPUT` |
| Generate a supervision report | Latest draftSections → `lib/supervisionDraft.ts` → `api/client.ts` | POST `/api/notes/supervision-report` | `graph/supervision_report.py::run_supervision_report_pipeline`; same-endpoint wrapper | Response only by default. generated_notes with P+top-level `persist=true` | T3; edit forwarding T7 | Connected. Current UI makes no save request; some additional history/goal/strategy fields disconnected | Auth. Graph itself needs no R/G/OpenAI |
| Transform a session note / termination document | Document assembly in `pages/SessionDraftPage.tsx` | No separate API for transformation itself | Note response also contains document drafts, but current screen assembles locally from edited draftSections | Screen state. No DB confirmation before export | Backend draft/export checks in T1; no full UI transformation E2E | Connected | No separate flag |
| Inspect source evidence for AI claims | `lib/groundingReview.ts` → `components/note/GroundingEvidenceReview.tsx` | `grounding` in note generate response; no separate evidence fetch | `graph/nodes.py` → `services/grounded_generation.py`, `raw_evidence_retrieval.py`, `claim_support_validation.py` | transcript_windows RPC → scoped transcript_turns; response source snapshot; evidence_items with P+save request | T5, T7, T8 | Conditionally connected. Default OFF. DEV fixture is separate | G; actual raw retrieval requires R+dense+tables/RPC+existing index |
| Store/index raw turns/windows | No calling screen | No dedicated product API | `services/transcript_storage.py::store_transcript_turns`, `transcript_windows.py::index_transcript_windows` | transcript_turns/transcript_windows and embeddings | T5 | **No automatic connection**. Material upload/STT/note persistence do not call it | G does not automatically execute the functions. Separate ingestion call, scope, DB/embedding required |
| Download final document | `pages/SessionDraftPage.tsx` → `api/client.ts` | GET `/api/documents/capabilities`, POST `/api/documents/export` | `services/document_export.py`; integrated route and Vercel wrapper | Returns file bytes. Only FastAPI records document_exports on a best-effort basis with P | T1, T2, T3 | Connected. No preceding DB confirm API call | Auth; DOCX by default, PDF capability, HWPX unsupported. Export itself does not require P |

## Persistence and execution prerequisites

`ENABLE_RAG`, `ENABLE_PERSISTENCE`, and `ENABLE_RAW_REGION_GROUNDING` are independent.
G alone does not create raw retrieval data. P alone does not start note/report persistence because
current UI requests do not request saving. Case schedule updates, draft APIs, recompose cache,
and FastAPI export history each follow their own conditions.

Response `confirmed_session_note` is a review projection also produced during generation.
It does not mean DB `generated_notes.confirmed_json` or actual confirmation status.
See the [Data Model](data_model.md) for entity meanings and conditions.

`api/client.ts` uses `VITE_API_BASE_URL` or same-origin and attaches the SDK access token as Bearer.
`vercel.json` rewrites draft-detail, record-detail, the case list (`/api/cases`), case dashboard/schedule, and client profile paths.
The export-history difference between integrated FastAPI and Vercel wrappers remains as shown above.

## Verification commands and coverage

Run backend commands in `backend/` and frontend commands in `frontend/`.
CI inclusion means the command exists in `.github/workflows/backend-smoke.yml` at the baseline commit;
it is not a record confirming a successful remote run of this commit.

| ID | Command | Coverage | Included in CI |
| --- | --- | --- | --- |
| T1 | `uv run python smoke_test.py` | Integrated FastAPI, stub generation/verification, input/file guards, audio modes and mock runtime, draft/cache/export regressions | Yes |
| T2 | `uv run python test_vercel_wrappers.py` | Wrapper auth, JWT forwarding, actor scope, confirm mocks, material extraction/export. Does not include case wrapper | Yes |
| T3 | `uv run python test_supervision_form.py` | Official form ordering, missing data, goals/strategies, progress table/transcript, DOCX/PDF structure | Yes, PDF job |
| T4 | `uv run python test_case_dashboard.py`; `uv run python -m unittest test_case_list` | Alias, transcript status, schedule validation, export row, dashboard route errors; case list aggregation, per-user isolation, drafts-table fallback, list wrapper | No |
| T5 | `uv run python test_grounded_generation.py`; `uv run python test_raw_window_pipeline.py`; `uv run python test_transcript_storage.py` | Flag OFF, source hierarchy/support handling, raw window/turn scope/assembly/storage helpers, static SQL checks | No |
| T6 | `pnpm verify:material-workflow`; `pnpm verify:audio-transcript-workflow` | Helpers applying material/audio input and source-contract checks | Yes |
| T7 | `pnpm verify:grounding-review`; `pnpm verify:counselor-edit`; `pnpm verify:case-list` | Grounding projection/stale markers, forwarding latest counselor edits to supervision; case list filter/search, next session number, session record grouping, page/client wiring | No |
| T8 | `pnpm verify:grounding-demo-browser` | DEV fixture browser behavior; synthetic demo without calls to note generate API | No |
| Build | `pnpm build` | TypeScript checks + Vite production build | Yes |

T8 requires a running DEV server (default `127.0.0.1:4174`) and Windows Edge or `EDGE_PATH`.
See the [README](../README.md#build-and-primary-checks) for execution order.

Distinguish these checks from actual Supabase policy application, Production user E2E, and real LLM
semantic accuracy. Passing transcript tests does not mean product ingestion is connected.
Research evaluations are in `research/` and are not imported by the product runtime.
See the [Grounding checkpoint](raw_evidence_grounding_checkpoint.md) for historical synthetic evaluation metrics.
