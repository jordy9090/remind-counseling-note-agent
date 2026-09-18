# Data Model

## Baseline and application status

The current migration/code baseline is `4815b4457af2c5ccbccbafe4e53687229988346c`.
On 2026-09-09, the user confirmed Production on Vercel at [remind.ai.kr](https://remind.ai.kr),
source `git`, branch `main`, the same SHA, state `READY`.
**This does not establish remote Supabase migration, RLS, or environment-variable application.**
The structures below are repository declarations and implementations; remote state requires separate verification.

Calling files, APIs, and tests are collected in the [Product Runtime Map](product_runtime_map.md).
This document covers entity meaning, ownership, relationships, creation timing, and current UI use.

## Shared ownership and persistence conditions

The real-user authentication path uses the Supabase-validated user ID as the actor.
Counseling tables have text `user_id` fields, not FKs to `auth.users`.
RLS on the existing counseling tables applies `auth.uid()::text = user_id` to the authenticated role.
`counselor_name` is a display value, not an authorization boundary.

The backend requests the DB with the user JWT and public key. Legacy/local service-role paths can
bypass RLS; distinguish these from service-level actor/scope checks.
Transcript Turn/Window policies check parent case/session ownership and relationships as well as user
matching. Not every table has the same composite FKs or parent-check policies.

| Condition | Controls |
| --- | --- |
| `ENABLE_PERSISTENCE` (default false) | Note/report persistence and confirmation, FastAPI export history. Not a global switch for all DB writes |
| Note input `persist=true` | Requests saving note generation results with `ENABLE_PERSISTENCE=1` + DB connection |
| Supervision top-level `persist=true` | Requests report persistence with `ENABLE_PERSISTENCE=1` + DB connection. Separate from persist inside session_input |
| `ENABLE_RAG` (default false) | Retrieval of stored case context/KB. Independent of `ENABLE_PERSISTENCE` |
| `ENABLE_RAW_REGION_GROUNDING` (default false) | Grounding graph path. Raw retrieval also requires `ENABLE_RAG=1` + dense + pre-existing index |
| `ENABLE_CASE_MEMORY` (default false) | Memory indexing on confirm. Does not block all reads of existing memory |
| `SAVE_RAW_INPUT` (default false) | Whether sessions.raw_input_text is saved. Does not block draft JSON/cache |

Current UI note/report generation does not request saving and does not call confirm/draft/recompose APIs.
The owned case list (`GET /api/cases`), client dashboard, record/draft restore, and schedule updates, however, are connected to the DB.
Distinguish API existence from UI invocation.

## Entities

### User

- **Meaning:** Supabase Auth user and session. The migration chain has no separate public users/profile table.
- **Ownership:** The validated Auth ID becomes user_id on counseling records. Only email-authenticated
  users are accepted; anonymous sessions are rejected by the API guard.
- **Relation:** Counseling tables connect through user_id values, with no auth.users FK/cascade.
  Deleting an Auth user alone is not guaranteed to delete all counseling records.
- **Created:** On email signup from Landing (`무료로 시작하기`); the account becomes usable after email
  confirmation.
- **Current UI use:** Connected; persisted sessions survive refresh, and logout ends the session.

### Case — cases

- **Meaning:** Counseling case ID, pseudonym, status, and schedule metadata.
- **Ownership:** user_id is the security owner; counselor_id records the server actor.
- **Relation:** id is a global text PK, not a per-user composite PK. The same case ID cannot be
  independently created for different users. Multiple Sessions/Generated Notes connect through case_id FKs.
- **Created:** Upserted by note/report generation paths that request persistence. No standalone case-creation UI/API.
- **Current UI use:** Case ID is used in input. The case list screen shows every case owned by the logged-in
  user (server-side `user_id` filter under RLS) with session/document/draft counts; selecting one opens the
  client dashboard where schedules are updated and saved records are reopened. Generation with `persist:true`
  upserts the case, so a generated session appears in the list after refresh or re-login.

### Session — sessions

- **Meaning:** Session number, date, title, transcription status, and saved input within a case.
- **Ownership:** user_id and the parent relationship through case_id. General table RLS checks the row's user_id.
- **Relation:** UUID PK, case_id FK, unique `(case_id, session_number)`.
- **Created:** Upserted by note generation with persistence requested. Supervision persistence finds and
  links an existing session; the report's session_id may be null if no session exists.
- **Stored content:** sanitized_input_text is a JSON string of the complete sanitized input.
  raw_input_text is null when SAVE_RAW_INPUT=false; the true path also applies masking in code.
  At save time, transcript_status is completed if transcript text exists, otherwise none.
  This value does not imply a background STT job.
- **Current UI use:** Session input is screen state. Saved sessions appear per case in the client dashboard
  (date, transcript status, summary status, linked documents and temporary drafts) and are counted in the case list.

### Generated Note — generated_notes

- **Meaning:** A record containing a generated document draft and confirmation status. note_type distinguishes document types.
- **Ownership:** user_id. API persistence paths record the actor.
- **Relation:** case_id FK, nullable session_id FK, optional source_note_id self FK.
  verification_reports and case_memory_chunks reference the note.
- **Created:** A new row is inserted on the successful Note API path with `ENABLE_PERSISTENCE=1` +
  request `persist=true`. draft_json stores the summary and additional JSON metadata when grounding is present;
  confirmed_json starts as an empty object. With `ENABLE_PERSISTENCE=1` + top-level `persist=true`,
  supervision finds and updates an existing report for the same case/session or creates one.
  This reuse path does not guarantee concurrent-request deduplication through a DB unique constraint.
- **Current UI use:** The generation response drives the screen. Default UI requests do not create DB rows.
  The dashboard reads document lists/summaries from existing generated_notes.

### Counselor-confirmed note — confirmation state in generated_notes

- **Meaning:** A state recording counselor-confirmed content on a saved note, not a separate table.
- **Ownership:** The Confirm API validates ownership relationships among the actor and saved note/session/case.
  It does not use the client's counselor_name as authorization.
- **Relation:** Updates confirmed_json, confirmation_status, counselor_edited, confirmed_at, and confirmed_by
  on the same note. Optionally becomes the source for memory chunks.
- **Created:** When an explicit confirm API request is processed with `ENABLE_PERSISTENCE=1` and an existing owned note.
- **Current UI use:** A confirm client/API exists but is not called by the current screen.
  The “최종 문서” screen or a completed download does not imply a DB confirmation-state transition.

**generated_notes.confirmed_json and response confirmed_session_note do not have the same meaning.**
The latter is a document projection returned by the generation pipeline and exists even on drafts with
`status: draft_requires_counselor_confirmation`.
Its name alone does not establish counselor confirmation, DB persistence, or completed memory indexing.

### Case Memory Chunk — case_memory_chunks

- **Meaning:** Masked text per field of a counselor-confirmed note, plus retrieval metadata/embedding.
- **Ownership:** user_id and counselor_id record the actor. Retrieval is scoped to the same user/case.
- **Relation:** case/session/source_note FKs. Unique `(source_note_id, field_type)`.
- **Created:** Nonempty fields are upserted during confirmation with `create_case_memory=true` and
  `ENABLE_CASE_MEMORY=1`. Embeddings are added when dense retrieval is enabled.
- **Current UI use:** The current UI does not create new memory because confirm is disconnected.
  Existing data is used indirectly during generation when RAG/dense are enabled.

### Transcript Turn / Window — transcript_turns, transcript_windows

- **Meaning:** A Turn contains a sanitized source utterance, speaker, turn index, and optional timestamps.
  A Window is a consecutive group of turns and an embedding for retrieval candidates. A raw region is
  a request-time object reassembled from source turns; there is no separate raw_regions table.
- **Ownership:** RLS/helpers check user_id=counselor_id and owned case/session relationships.
- **Relation:** Both tables have case/session FKs. Turns are unique by `(session_id, turn_index)`;
  windows by `(session_id, start_turn_index, end_turn_index)` and source_ref.
  Windows use session and index ranges, not individual FKs to each turn.
- **Created:** When separate storage and indexing helpers save turns and create windows.
  Defaults are 6-turn windows with stride 3 and an added terminal window. Migration vectors have 1536 dimensions.
- **Current UI use:** **Ingestion is not automatically connected to the product flow.**
  Document upload, STT, and note persistence do not call these helpers.
  With a pre-existing index and grounding + RAG + dense, they are used indirectly for historical source
  retrieval and the evidence UI. Migrations/flags alone do not automatically convert text in existing sessions.

### Evidence / Verification — evidence_items, verification_reports

- **Meaning:** Evidence contains source links/snapshots for document items; Verification contains review reports.
- **Ownership:** Each has user_id and owner RLS.
- **Relation:** Both have case/session FKs. Verification also has a note_id FK; Evidence has no direct note_id.
- **Created:** Inserted alongside a requested note save. With grounding OFF, evidence rows store mapped-item
  content and refs; with it ON, they store cited source snapshots. Verification stores report_json.
  Persistence uses multiple REST requests, not one DB transaction around the entire operation.
- **Current UI use:** Review information from generation responses is displayed regardless of persistence.
  The grounding UI uses response source snapshots without a separate DB evidence lookup.
  Marking edits stale is distinct from revalidation/DB confirmation.

### Document Export — document_exports

- **Meaning:** Export-attempt metadata (document type, format, title, status, error), not storage for file contents.
- **Ownership:** user_id owner RLS.
- **Relation:** Contains case_id and session_number values, with no case/session FKs.
- **Created:** Integrated FastAPI export records completed/failed on a best-effort basis with
  `ENABLE_PERSISTENCE=1` + DB connection. Logging failure does not prevent returning the file.
  processing is permitted by the schema, but current export is synchronous.
  The Vercel export wrapper does not call this recording function.
- **Current UI use:** File downloads and dashboard lookup of existing history are connected.
  Do not expect a Vercel download to create a new history row.
  File bytes are returned in the response; confirm API invocation is not required before download.

### Temporary Draft — counseling_drafts or temporary disk JSON

- **Meaning:** A workspace snapshot containing the input form, selected items, edited draft, generation response, and related state.
- **Ownership:** Supabase uses user_id owner RLS and a hash key based on user+draft ID.
  Disk fallback separates actors into their own directories.
- **Relation:** case_id/session_number are values without case/session FKs.
  The snapshot is independent of Generated Note/confirmed_json.
- **Created:** Draft POST upserts when a Supabase connection exists; otherwise it saves JSON in
  TEMP_DRAFT_DIR or the system temporary directory. The same API supports reading/listing.
- **Current UI use:** Disconnected. The current temporary-save button only displays guidance.
- **Retention boundary:** ENABLE_PERSISTENCE/SAVE_RAW_INPUT do not block this storage.
  The form may contain input text. Temporary disk does not guarantee sharing across serverless instances or long-term retention.

## Supporting storage

- `kb_documents → kb_chunks`: Document templates and ethics/privacy KB. Shared materials separate
  from user counseling records; declared policies allow authenticated reads. No product UI path for authoring KB content.
- `retrieval_logs`: Retrieval-service diagnostic metadata with user_id ownership. Does not imply completed remote operational audit logging.
- Recompose cache: Stores result JSON on local disk with actor-inclusive cache keys.
  Uses `RECOMPOSE_CACHE_DIR` or the system temporary directory, independently of `ENABLE_PERSISTENCE`.
  The current UI does not call the recompose API.
- Original PDF/DOCX/TXT/audio uploads use temporary files and clean them up. Not retaining original files
  is a different condition from not retaining extracted text, sanitized input, or draft JSON.

## Migration chain

The source of truth is `supabase/migrations/`. The sequence below is present in the code;
it does not mean the same sequence has been applied remotely.

| Migration | Contents | Remote application status |
| --- | --- | --- |
| 20260717000100_baseline_schema | Base case/session/note/evidence/verification/KB/draft schema | Unverified |
| 20260717000200_pgvector_hybrid_rag | Vectors, case memory, retrieval logs, KB search, RLS enablement | Unverified |
| 20260718000100_case_memory_unique_confirmed_fields | Confirmed-field memory uniqueness and related changes | Unverified |
| 20260823000100_user_owned_counseling_data | user_id, owner policies/grants | Unverified |
| 20260826000100_case_memory_rpc_user_scope | Canonical user scope in memory RPC | Unverified |
| 20260901000100_case_schedule_and_transcript_status | Schedule and transcription status | Earlier docs treated it as applied; current ledger unverified |
| 20260902000100_document_exports | Export history | Earlier docs treated it as applied; current ledger unverified |
| 20260903000100_raw_evidence_layer | Transcript turns | Release review/application was pending at the previous checkpoint; current ledger unverified |
| 20260903000200_transcript_window_retrieval | Transcript windows and match RPC | Release review/application was pending at the previous checkpoint; current ledger unverified |

SQL for `evidence_episodes` and `match_evidence_episodes` is research material under
`research/raw_evidence_experiments/supabase/`, not part of this chain or a product prerequisite.
The current DB schema baseline is `supabase/migrations/`.

Remote verification requires checking the target project's migration ledger as well as tables, policies,
grants, RPCs, and data readiness for each feature. This documentation cleanup did not access or change the DB.
