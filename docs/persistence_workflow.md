# Save, confirm, and restore workflow

PR #17 uses `codex/persistence-workflow`. Review-fix baselines (2026-09-11):
PR head `035b273649a95435f3a0072654acc05813897d4b`, fetched `origin/main`
`6d40dc6e8743eae539993a462c1c757aa142a55f`.
The actual merge conflict was limited to added scripts in `frontend/package.json`;
both authentication and persistence verification commands are retained.
Authentication implementation and other upstream changes are taken unchanged from main.

## API contract

| Operation | Behavior |
| --- | --- |
| POST /api/notes/drafts | Saves counselor input and edited workspace; later saves reuse the draft ID. |
| GET /api/notes/drafts and /drafts/{draft_id} | Lists/restores owned temporary workspaces. |
| POST /api/notes/generate | Uses persist:true; a successful persistence report and note ID are required for confirmation. |
| POST /api/notes/confirm | Saves current counselor sections while preserving the original AI draft. |
| GET /api/notes/records/{note_id} | Returns full draft_json, confirmed_json, and status; dashboard excerpts cannot restore full text. |

The detail endpoint reuses note → session → case ownership checks and the authenticated
Supabase Bearer token. Responses use `Cache-Control: private, no-store`.
The Vercel wrapper `/api/notes/record?note_id=...` and rewrite must ship with the frontend.
No database columns, migration, RLS policy, auth behavior, or AI prompt/model changes are introduced.

## Confirmed records

- Direct strings, objects with a string `text`, and `sections[field]` strings use the same
  reader in the restore UI. Direct fields take precedence over secondary section values.
- A present empty string is an intentional counselor edit. Missing fields are distinct and
  omitted from confirmed documents instead of receiving AI text or placeholders.
- `workspace_sections` preserves custom sections, order, visibility, and empty content;
  a saved empty array is valid. Malformed records report errors before changing the workspace.
  Confirmed reads never fall back to `draft_json`.
- Reconfirmation builds canonical fields from the current sections. Absent fields cannot
  reappear from the AI original. Canonical fields support the dashboard, and `sections`
  supports the existing case-memory contract.
- Temporary restoration preserves its edits. A separately loaded server record establishes
  the confirmed fingerprint without overwriting those edits. Further edits remain unconfirmed.
- This UI sends `create_case_memory:false`. Confirmation applies to the session summary;
  separately edited final documents belong to temporary workspaces and exports.

## Temporary draft allowlist

`frontend/src/lib/temporaryDraft.ts` projects requests before transmission.
`backend/app/services/temporary_draft_payload.py` enforces the same allowlist before
Supabase or local disk storage and on draft detail/list reads. The shared synthetic fixture
`frontend/scripts/fixtures/temporary-draft.json` exercises both boundaries.

| Preserved | Excluded from temporary JSON |
| --- | --- |
| Current session input, including counselor-written or explicitly applied transcript, memo, previous/test summaries, goals, tags, and observations | Unknown nested form fields, including attachment copies |
| Edited summary ID/title/content/visibility and final-document content/order | Section evidence excerpts and grounding/source caches |
| Visible AI summary text, warning/missing-item lists, and owned note ID | result.full_response, sanitized-input duplicates, retrieved evidence, grounding, evidence_check excerpts |
| Edited supervision text, table cells, selected report transcript excerpts, metadata, and review state | Supervision evidenceIndex and unrecognized nested caches |
| Attachment identity, filename/type, counts, processing metadata, applied targets, and unapplied-edit flag | File bytes, blob URLs, extractedText, transcriptText, segments/words, acoustic text, speaker map, lastAppliedTranscriptText, lastAppliedNonverbalNotes, provider warning/error caches |

Projection does not mutate the in-memory workspace. Failed saves preserve input, summary
edits, and unapplied attachment edits. Duplicate requests are blocked while saving.
No raw cache is moved into localStorage or IndexedDB.

After reload, attachments are metadata-only and require reattachment. The screen explains
that previews and unapplied transcript edits cannot be restored. Preview/apply actions require
text, and transcription requires the file. Counselor-applied input remains editable and usable
for generation. Reattach the file to extract/transcribe again. Save feedback states this limit
before leaving the page.

Legacy responses are projected without rewriting or deleting stored rows. Previously stored
raw caches are not purged. Retention decisions require separate authorization.
PR #19's sanitized transcript evidence storage is separate and unchanged.

## Failure and restoration limits

- Generation can return HTTP 200 with stored:false. Keep the AI draft, show failure, and disable
  confirmation. Temporary saving can preserve editable text without regeneration.
- Missing tokens fail before persistence requests are sent. Server authorization is unchanged.
- Unreadable linked confirmation status permits temporary edit restoration but disables
  confirmation until the original record can be verified.
- Note detail alone does not restore original session input; use the temporary workspace.
- Evidence previews and source verification caches are not restored. Recheck sources before
  treating restored assertions as verified. Edited report content is retained.
- Existing generation writes are not transactional; partial-write behavior is unchanged.

## Local verification

Use synthetic data only. The Python harness exercises real routes, generation stubs, ownership
checks, and storage helpers with in-memory Auth/REST substitutes. Browser audio responses are
synthetic; document extraction uses a synthetic TXT file against the local API.
No hosted DB, counseling data, paid generation, embedding, or transcription is used.

From the backend directory, using the project's Python environment:

```powershell
python -m unittest test_persistence_workflow test_case_dashboard test_vercel_wrappers test_auth_guard test_transcript_storage test_raw_window_pipeline
```

From the frontend directory:

```powershell
npm run verify:persistence-workflow
npm run verify:counselor-edit
npm run verify:material-workflow
npm run verify:audio-transcript-workflow
npm run verify:grounding-review
npm run build
```

Start `python test_persistence_workflow.py --serve` from backend in one terminal.
Start the frontend in another:

```powershell
$env:VITE_SUPABASE_URL='http://127.0.0.1:8017'
$env:VITE_SUPABASE_PUBLISHABLE_KEY='synthetic-public-key'
$env:VITE_API_BASE_URL='http://127.0.0.1:8017'
npm run dev -- --host 127.0.0.1 --port 4174 --strictPort
```

Run `npm run verify:persistence-browser` from frontend with Node 22 and Windows Edge
(`EDGE_PATH` can override the executable). It covers upload/cache exclusion, applied input,
reattachment notices, failed-save edit preservation, generation/edit/confirm/reopen/reconfirm,
legacy formats, empty/missing fields, malformed confirmed restore, token gating, and viewport
boundaries. Synthetic captures go to `frontend/screenshots/persistence/`.

## Integration and rollback

Ship the API and frontend together. Backend-first rollout filters old requests safely;
old attachment previews require reattachment. A frontend rollback must retain the server
allowlist to avoid reintroducing raw caches. No database rollback or deletion is needed.

Hosted Supabase Auth/RLS and two-user isolation require separately authorized environment
verification. Local substitutes do not establish hosted RLS correctness.
No main merge, Production deployment, remote configuration change, or paid API call is part
of this task.

## Hosted release follow-up (2026-09-14)

The release follow-up is separately authorized; the original local-only results above remain
distinct from hosted verification. Candidate `f076a55` passed normal email login, input/TXT
application, temporary save/reload, counselor edit/confirmation, logout/login, full confirmed
note restoration (including an intentional empty field), and edited-report workspace restoration.
The generation endpoint returned `stub:true` with `stored:true`; this does **not** establish a
successful live AI generation. Release remains blocked until the deployed generation configuration
or failure cause is resolved and actual generation is verified within the approved cost scope.

Normal A/B JWT checks against the shared Supabase project `bgjapctiawosgpjcyfuq` found no
cross-account reads or updates: backend detail/confirmation/schedule requests returned 404;
direct RLS reads and updates for the synthetic case, session, generated note and temporary draft
returned zero rows for B. A could retrieve its saved draft directly, confirming the backend's
temporary persistence target and exclusion of attachment raw caches. These checks used public
keys and normal user JWTs, never administrator credentials. Deployed configuration values and
Production smoke testing remain unverified.

The hosted report exposed two conversion defects: full-transcript mode omitted the counselor's
edited summary from visible report content, and the `상담사:` speaker label dropped counselor
turns. The follow-up preserves the existing full transcript and adds the existing summary table
alongside it; both `상담사:` and `상담자:` labels are recognized. Empty summary values remain empty.
`python -m unittest test_supervision_form` passes all eight tests, including both regressions.
The conversion pipeline is deterministic and makes no external model calls. Auth, storage
policies, AI prompts/models, and the server temporary-draft allowlist are unchanged.

The follow-up Preview (`1664723`) returned the reviewed summary and all four synthetic speaker
turns in the real deterministic conversion response. Mobile visual inspection also found that
report content buttons inherited the global no-wrap rule, clipping transcript sentences.
The content button now explicitly allows wrapping; short action buttons retain their styling.
Frontend typecheck/build passed after this scoped wrapping fix (the existing bundle-size warning
remains). The owner confirmed Preview has `USE_STUB=0` but no `OPENAI_API_KEY`; the
`Settings.stub_mode` expression therefore selects stub mode before model execution. Add the
server-only variable to the Preview environment and deploy again before the single authorized
live generation. Production variable presence is still unverified; no secret was read or copied.

The pre-release Production deployment predates that allowlist and is not a safe full rollback
target after this release. Use a forward recovery commit that retains the allowlist and its
draft-store read/write projections; verify the affected flow before switching Production.
