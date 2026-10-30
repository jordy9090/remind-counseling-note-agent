# Voucher document export

Implemented against `9161b60b1c597c8d580d7b24b5c126f51c32be32` on 2026-10-30 (Asia/Seoul). Migration `20261030000100` was applied to project `bgjapctiawosgpjcyfuq`. PDF export was enabled in Production at commit `23f2d96` (deployment `dpl_62r96JbcTpZ1FmM8YnVAULsioRuB`), after real synthetic persistence and Production smoke checks. The disposable account and all related rows were removed, with zero remaining users, Auth sessions, cases, sessions, notes and vouchers verified.

## PDF preview compatibility repair

The native `<iframe>` PDF viewer produced a blank preview in the Codex in-app browser. `VoucherPdfPreview` now renders the authenticated response bytes locally with pinned PDF.js 6.4.299 and a same-origin bundled worker. No PDF content goes to an external viewer. The component exposes loading/failure states, cancels stale work on replacement/unmount and permits review only after all pages render successfully.

The existing synthetic browser test now checks nonblank canvas pixels, both official forms, reviewed download/reopening, and an invalid-PDF response that must clear old content and block review even when both acknowledgments are checked. Build, the complete local flow, and the focused preview retry/render-error scenario passed. DB and Auth checks from the released commit are reused because those paths did not change. React hook/lifecycle and scoped security review cover only the changed renderer and its integration; no authentication, database or model configuration changed.

The generated Form 10 HWPX was opened and visually rendered by the official Polaris Office Tools web engine on 2026-10-30. This is an actual renderer check, but not an editor save/reopen qualification. Desktop Polaris window capture remains unavailable; the web editor origin was denied by browser access control. HWPX remains disabled pending both-form edit/save/reopen checks and resolution of its stale preview image.

## Delivered flow

- The document archive and confirmed-session document conversion screen open the voucher workspace.
- Form 10 imports 1–8 owned, confirmed session notes. The counselor supplies the voucher session number, actual delivery date and delivery attestation. Ordinary session numbers are never substituted for voucher numbers.
- Form 26 accepts a manual service plan before any session note exists.
- Existing privacy processing runs before preparing the PDF preview. The reviewed snapshot is immutable; editing creates another candidate. Reopening or downloading never reruns a model or privacy transformation.
- A reviewed document can be reopened, downloaded as PDF, or deleted. Names, birth dates, addresses, contact details and signatures in administrative cells remain blank for offline completion.
- Text that cannot fit or uses an unsupported glyph is rejected with the affected field. Nothing is silently truncated, reduced to an unreadable size, or summarized by a new model.

## Specification decisions

The supplied v1.0 specification correctly identifies the current code and official form hashes. Its core invariants are retained. These changes deliberately keep the first implementation smaller:

1. One immutable `voucher_documents` table replaces separate episode, draft, revision and operation tables. `user_id + operation_key` gives prepare-request idempotency. There is no voucher billing ledger, episode lifecycle, cross-document duplicate-session enforcement, or government-portal submission.
2. Form 10 maps only confirmed `session_content`, `counselor_intervention` and `client_response`. `workspace_sections` is authoritative, including visibility, deletion and deliberate empty text. Drafts, raw transcripts, reflection, supervision and relational insights are excluded. Existing confirmed records can be read without fetching the original session input. Test scores are entered explicitly; they are not inferred.
3. The PDF grid comes from the official PDF. All original text is removed before fixed labels are re-typeset with bundled OFL Nanum Gothic. This removes example content from the searchable text layer, not merely behind a white rectangle. The source PDF's empty second page in Form 10 is omitted.
4. HWPX generation fills designated XML cells in the original archive, but its public capability stays false until an actual editor open/edit/save and rendering check. The user selected Polaris Office for qualification; a Polaris pass must not be described as a Hancom pass. XML validity is not application compatibility. The source preview image is still a blank/example-form preview, not a rendered preview of the current values; this also needs resolution before HWPX release.
5. Source hashes are checked at preparation and review. This is not an atomic revision lock across concurrent note edits. A previously reviewed export intentionally remains the reviewed historical snapshot; it does not silently adopt a later note revision.
6. Saved candidates appear in the voucher workspace, not in the existing generic `document_exports` attempt log. There is no automatic retention expiry. Explicit document deletion and case/account/source-note deletion are supported by the service and migration.

## Security and runtime

- All voucher routes require a verified `AuthenticatedActor`; shared preview tokens cannot access stored voucher data.
- All snapshot operations forward the verified user's JWT through the existing actor-scoped storage client. Production has no service-role key; this feature requires none. Source reads additionally follow the existing authenticated note/session/case ownership chain.
- RLS permits authenticated users to select, insert, acknowledge and delete only their own snapshots. Insert triggers check case/source ownership and reject pre-reviewed rows. Update triggers allow only the first review acknowledgement. The fingerprint detects accidental changes; it is not a server signature. A user with their own JWT can write their own rows through the Data API; privacy status is an application processing report, not a tamper-proof certification.
- Case/account foreign keys cascade; a source-note deletion trigger removes derived documents. Insert-time source row locks serialize source deletion against snapshot insertion. These policies and both insert/delete race orders passed in an isolated PostgreSQL 17.11 cluster with synthetic rows.
- PDFs and JSON responses use private/no-store. Downloads use UUID-only filenames, authenticated binary responses and no public storage URLs. Templates are fixed local files with pinned hashes; user content is escaped, with no uploaded templates or remote resource fetching.
- `ENABLE_VOUCHER_DOCUMENTS=1` enables the routes only after the migration and release checks. Default is disabled. The additive migration is compatible with the previous application deployment.
- The existing deidentification service can use its configured model during preparation. Mapping and rendering do not call a model. Tests disabled entity extraction and used only synthetic content; they do not prove live model quality.
- Any change to the privacy policy requires a new `POLICY` version. Retain template bundles needed by existing snapshots before upgrading templates; this first version fails closed when the bundle fingerprint differs.

## Sources and assets

Official source: [Gangnam District provider documents](https://www.gangnam.go.kr/board/B_000060/1071230/view.do?mid=ID03_01). Asset hashes are in `backend/app/templates/vouchers/2026/manifest.json` and match the supplied specification. Font license: `compiled/OFL.txt`.

The publisher page has a KOGL Type 4 notice, while the forms themselves permit institution-specific changes. The scope of commercial template redistribution has not been resolved here. This is a release follow-up, not a claim that completing or using the form is prohibited. No external publication was performed.

`backend/compile_voucher_templates.py` reproducibly extracts fixed-text positions and recompiles the PDF backgrounds. Extraction uses the already installed local PDF authoring environment (`pdfplumber`); runtime needs only existing ReportLab, pypdf and lxml dependencies. No remote document conversion service is used.

## Validation ledger

Local working-tree candidate, base SHA above; no deployment ID. Results recorded at 2026-10-30 02:09:37 KST. The final code SHA is recorded in the local `tmp_ab/voucher-validation-ledger.json` after commit.

| Check | Result | Evidence / limit |
|---|---|---|
| `python -m unittest backend.test_voucher_documents -v` | PASS, 14 tests + 1 focused validation test | Mapping, hidden/deleted/empty fields, wrong owner/case, source changes, immutable review, privacy before preview, PDF bytes, overflow/glyph checks, HWPX XML, local/Vercel route parity. Added `MappingTests.test_unrendered_fields_cannot_be_hidden_in_snapshot` passed separately. Model/DB/Auth replaced by synthetic test doubles. |
| `python -m unittest backend.test_document_rich_text backend.test_persistence_workflow backend.test_vercel_wrappers backend.test_auth_guard` | PASS, 54 tests | Existing generic export, persistence, wrapper and auth regressions. Existing WeasyPrint native-library warning; ReportLab output exercised. |
| `npm run build` | PASS | TypeScript and Vite; existing bundle-size and Browserslist warnings. |
| `node scripts/verify-voucher-browser.mjs` | PASS | Real React UI, local HTTP API, PDF renderer, memory storage: import → edit → preview → review → download → reload/reopen → edit/new review; manual plan; HWPX disabled. Reopened PDF byte-identical. |
| `VOUCHER_SCENARIO=preview_retry node scripts/verify-voucher-browser.mjs` | PASS | Focused test after the preview retry change: sanitized candidate reused; failure clears the old PDF and prevents approval; retry succeeds without duplicate snapshots. |
| `npm run verify:persistence-workflow`; `node node_modules/typescript/bin/tsc --noEmit` | PASS | Existing frontend persistence regressions and final TypeScript check. |
| PDF visual inspection | PASS | Both synthetic forms; original grids preserved, values inside cells, identity/signature cells blank, no sample bank account. Form 10 second source page confirmed blank. |
| Scoped manual security diff review | PASS after actor-JWT/RLS revision | Reviewed routes, ownership chain, fixed renderers, snapshot storage, migration, UI and local test harness. Tested database enforcement and documented the distinction between owner-editable Data API input and server privacy certification. No repository-wide scan or external reporting integration. |
| PostgreSQL migration/RLS/cascade/concurrency execution | PASS, 2026-10-30 | `python backend/tests/verify_voucher_postgres.py --psql <portable-psql> --port 55439`; PostgreSQL 17.11, local synthetic schema. Owner CRUD/review, other-user/anonymous isolation, forged ownership/source/pre-review rejection, immutability, idempotency, source/case/account cascades, both insert/delete race orders. Zero fixture rows after cleanup; server stopped. |
| Actor-JWT regression | PASS, 2026-10-30 | 15 voucher tests plus `ServiceTests.test_all_snapshot_operations_forward_user_token_without_admin_key`; GET/POST/PATCH/DELETE forward the authenticated token. Browser flow rerun once after storage change; zero synthetic snapshots after cleanup. |
| Polaris HWPX open/edit/save and PDF comparison | BLOCKED | Installed Polaris app found, but native control returned off-monitor capture and stale-element errors. Actual document rendering not verified; HWPX capability false. |
| Preview/Production deployment and live model | NOT RUN | No deployment or external inference performed. |

The first HTTP test attempt was blocked in Windows' sandboxed asyncio loopback socket creation; rerunning with local socket access passed. Two initial browser locator attempts failed after successful import because implicit textarea labels included text; explicit accessible field names and matching selectors resolved this. These were not model or database successes.

Cleanup: all browser-created in-memory snapshots were deleted and zero remaining rows verified. No live accounts, sessions, counseling records or paid requests were created. Synthetic inspection files stay in ignored `tmp_ab/`.

## Before enabling a deployed version

1. Apply the locally tested migration to the verified deployment database, then verify the actor-JWT persistence path using synthetic records.
2. Confirm the template reuse terms. Qualify HWPX in Polaris separately; PDF can remain the only enabled format.
3. Deploy this exact tested code to Preview, set the feature flag there, and run one real persistence flow using synthetic records. Enable Production only after the user-authorized release checks; retain the current healthy deployment for rollback.
