# Restricted real-data PoC release checklist

Decision: **HOLD real data and production rollout** until the blocked environment and policy checks are signed off. This is an engineering evidence ledger, not a security certification or legal opinion.

## Completion criteria and boundaries

1. Independently review PR #100, reproduce surviving P0/P1 paths with synthetic inputs, and apply narrow corrections to that branch.
2. Provide safe, reproducible authentication/RLS verification procedures and automated local checks; distinguish mock results from installed database policy.
3. Account for deletion targets, retained derivatives, caches, temporary files, failure/retry behavior and backup blockers without deleting real data.
4. Restore usable saved evidence only for unchanged, supported claims; preserve final notes and never reconstruct deleted originals.
5. Inspect application errors and tracing for sensitive content and close locally reproducible exposure paths.
6. Keep small commits, independent review, relevant CI and this checklist current; use stacked Draft PRs for separate P1 changes.

Authorized: source/templates/tests, synthetic data, mocks, local isolated worktrees, commits and Draft PRs. Not authorized: production access/deployment, main merge, real data or keys, production DB changes, real-data deletion, legal/contract decisions or major architecture replacement. Operational checks below remain BLOCKED while local work continues.

Baseline checked 2026-11-19 07:33 UTC: main `f942db4ecb6e696d75022d3f01a52b8bf2a37cf0`; PR #100 `536d2047305257fd8b12268a2503e606ad98a2a9`, open Draft, no submitted human reviews. Existing dirty development checkout is untouched. Historical `SECURITY_POC_REVIEW.md` describes the November 17 local snapshot; `SECURITY_POC_REMEDIATION.md` describes the newer PR baseline. Historical findings must be revalidated, not assumed current.

Follow-up scope, 2026-11-19: inspect the latest PR #105 CI, repair the deletion/transcript concurrency failure, obtain passing CI, and record PR #104 evidence and unresolved gates here. Work stays on `codex/poc-deletion-scope`, stacked on PR #104 at `943cf8d4dd3246d73abeb883447c6bc23a0a662f`. The initial fetch confirmed main remained `f942db4ecb6e696d75022d3f01a52b8bf2a37cf0`. Only synthetic fixtures, mocked identities/services and the isolated disposable CI database are authorized. No main merge, deployment, live account, existing database or real data is part of this follow-up.

## Completed

| Item | Evidence | Limits |
| --- | --- | --- |
| PR #100 baseline implementation and CI | [PR #100](https://github.com/jordy9090/remind-counseling-note-agent/pull/100); backend 25 and frontend 12 new mock regressions; [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942429), [security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942399) passed at `536d204` | Reused because unchanged; not proof of installed RLS or deployment settings |
| Original-input column and recompose cache guards | `poc_mode` overrides raw-input and cache flags; effective policy exposed to UI | Existing copies, drafts, sanitized narratives, excerpts and downloads remain sensitive |
| Guest handoff removed | Legacy pending summary discarded without display/import; signed-in save remains covered | Does not establish browser/device backup erasure |
| P0 follow-up: reviewed-history consumption | `398344b`: the graph now uses the same effective review predicate as receipt validation; a real graph-node/prompt regression proves counselor-masked history is not fetched again | Five synthetic history controls; no live model |
| P0 follow-up: shared identity disabled throughout PoC APIs | `398344b`: common dependency requires a verified bearer in PoC, authentication has no service-key fallback, startup rejects missing real-auth/public configuration | Six synthetic checks and independent review; actual participant roster remains blocked |
| PR #104: parent ownership and immutable scope | `943cf8d`: [disposable PostgreSQL CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44484825403) applied 18 source migrations and passed all 469 generated SQL assertions, `counseling_parent_scope.sql` and `beta_case_retention.sql`; zero failures and zero remaining synthetic rows. [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44484825557) and [security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44484825417) also passed | Resolves the 48 forged-parent failures recorded for #102 in the disposable fixture. Uses SQL roles/claim mocks, not signed JWTs or deployed Supabase policy; no submitted human reviews or inline review threads as of this follow-up |
| PR #105: atomic input deletion and concurrent transcript writes | `804bfda`: [disposable PostgreSQL CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864904) applied 19 migrations; 469 assertions, four SQL contract files and all five two-connection ordering scenarios passed. [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864839) and [security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864876) passed | Original source/transcript rows are removed, late inserts rejected, confirmed notes and other declared derivatives retained. Zero synthetic rows remained and the disposable container/tmpfs were removed. No deployed database was changed |
| PR #104 beta cascade follow-up, exercised on #105 | `beta_source_note_cascade.sql` passed at `804bfda`, covering source-note `SET NULL` cascades during expiry and withdrawal, unrelated-case preservation and late-write rejection | Closes the recorded cascade concern for these synthetic source-note cases; this contract was not part of #104's original two-file SQL run |

## Remaining: prioritized engineering work

| Priority / item | Evidence and action | Status / owner |
| --- | --- | --- |
| PR #100 follow-up integration | Verify CI for reviewed-history/identity corrections; both configuration templates now require real-user auth | Local green; CI pending |
| P1: reopened evidence projection | Historical failure still appears in `noteFromRecord`; retain only owned, validated saved excerpts for unchanged claims | Isolated reproduction/fix in progress; stacked branch `codex/poc-evidence-reopen` |
| P1: residual retention and cleanup | Inspect deletion response semantics, partial failures, scratch cleanup and detector jobs against existing retention tools | Source review in progress |
| P1: tracing and diagnostics | Inspect graph/LLM callbacks in addition to application exception handlers; synthetic egress/log canaries | Source review in progress |
| Release verification pack | Safe preflight and disposable-database RLS/ownership procedure; no remote targets by default | In progress |
| P1: broader PR #104 lock contention | The parent-scope trigger still uses shared parent locks. Its general child-update/parent-delete and concurrent parent-update combinations are outside the five session-input deletion scenarios in #105 | Remains open for targeted disposable concurrency tests; do not interpret the passing single-transaction ownership suite as proof that every lock ordering is safe |
| Release integration and installed-policy parity | PRs #104 and #105 remain stacked Drafts. An authorized release still needs exact migration/configuration parity, deployed authentication/RLS checks, and privileged operator review | BLOCKED outside this task; no main merge or deployment |

## Blocked: evidence or approval required outside local engineering

| Item | Required evidence / safe verification | Why blocked |
| --- | --- | --- |
| Deployment/version/identity | Exact frontend, API, audio and detector revisions; approved origins/TLS; invitation/participant settings; real JWT enforcement; effective PoC flags | Actual server access and configuration attestation are not authorized |
| Installed RLS, grants, storage and RPCs | Two synthetic users in an explicitly designated disposable environment; direct SELECT/INSERT/UPDATE/DELETE, relationship and RPC checks, including unauthenticated roles | No production DB access or real credentials; local PostgreSQL tooling availability must be recorded |
| Existing retained data and backups | Approved inventory, retention periods, deletion authority, backup/PITR expiry and restore reconciliation; provider deletion evidence | Real-data cleanup and retention/legal decisions require owner approval |
| Key/operator access | Redacted access matrix for data, signing/encryption keys, privileged accounts, support access and backups | Requires actual infrastructure/secret-manager permission review; no keys may be supplied to these tests |
| Vendors and legal basis | Actual processors, locations, training/retention terms, subprocessors, consent/legal review | Contract and legal review are separate external decisions |
| Monitoring outside the app | Proxy/APM/crash-dump configuration and synthetic canary observation in an authorized environment | Local mocks cannot establish external collector behavior |

## Consent and privacy notice: technical facts and limits

Source-backed facts are conditional on deployment of the reviewed version with its required settings. Approved text versions are scoped by actor/purpose/body hash; changing a request requires renewed approval. PoC saves omit the optional original-input column and do not use recompose disk caches. Guest results are not automatically imported into another account. Application errors use fixed messages in tested paths.

Do not claim that no identifiable content is retained, that pseudonymization is complete, that all processing is local/self-owned, that only counselors can decrypt data, that original-input deletion erases summaries/drafts/downloads/backups, or that approval proves legal compliance. Existing one-hour receipts can retry the same approved version; browser edits do not revoke a token for an older approved body. Unresolved history/evidence paths above must close before describing them as verified.

## Validation ledger

For each new change record commit, environment, exact command/check, UTC time, result and synthetic cleanup. Prior passing checks above are reused until their relevant code/configuration changes. No deployment or real accounts are part of the local verification environment. Optional scanner integration previously rejected this Git worktree; no scanner pass is claimed, and focused independent source review is required.

| Code version | Environment / check | Result and time | Cleanup |
| --- | --- | --- | --- |
| `536d204` / main `f942db4` | Source/Git/PR metadata assessment; one initial fetch | Clean task worktree; unchanged baseline; 2026-11-19 07:33 UTC | No data created or deleted |
| `536d204` + regression additions | Protected `test_poc_reviewed_history`; `test_poc_auth_boundary` | Red: reviewed-history prompt restored the removed synthetic identifier; shared identity and service-key fallback controls failed. Positive non-PoC controls passed. 2026-11-19 before correction | In-memory mocks; scratch removed |
| `398344b` | `python backend/tests/run_poc_review.py test_poc_auth_boundary test_poc_reviewed_history` | 11 passed; 2026-11-19 07:38 UTC checkpoint | No external accounts/data; scratch removed |
| `398344b` | Protected runner `--legacy test_auth_guard test_reviewed_history test_iwinv_review test_security_access_boundaries` | 54 passed; 2026-11-19 07:38 UTC checkpoint | No network or credential access |
| `c37733e` | GitHub Product CI 44481397938 / security CI 44481397897 | Security suite, frontend build and PDF export passed. Backend discovered one stale mock setting (401 vs legacy 503), corrected by explicitly selecting non-PoC mode in that legacy test | Ephemeral CI; no real credentials |
| `c37733e` + test correction | `python backend/tests/run_poc_review.py --legacy test_case_dashboard` | 19 passed; 2026-11-19 07:50 UTC checkpoint. Product CI now also covers PRs targeting stacked branches | Mock store only; scratch removed |
| PR #104 `943cf8d4dd3246d73abeb883447c6bc23a0a662f` | GitHub Actions disposable PostgreSQL 15; `python3 backend/tests/run_poc_database.py --run-disposable`; [run 44484825403](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44484825403) | Passed 469/469 assertions, 18 exact source migrations and both SQL contract files at 2026-11-19 08:07:19 UTC. Product/security workflows linked above also passed | Zero remaining synthetic rows; container/tmpfs removed; no live Auth accounts |
| PR #105 `44ed8852d0c182594634f26702f8cbfb8c806964` | Same disposable command; [run 44486103280](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44486103280) | Failed `session_input_deletion.sql` with `42501` before concurrency at 2026-11-19 08:16:30 UTC; Product/security CI passed | Owned disposable container/tmpfs removed; no persistent database used |
| `fc37ffe9fa40f94571842c41ec8d7ea5d9c4637c` | Local Windows: `python backend/tests/run_poc_database.py --static`; `python -m unittest discover -s backend/tests/poc_database -p test_runner.py -v` | Static inventory and all four runner safety tests passed before the 2026-11-19 08:33 UTC checkpoint | No database, accounts or external data created |
| `fc37ffe9fa40f94571842c41ec8d7ea5d9c4637c` | Same disposable command; [run 44488560140](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488560140) | Fixture privilege corrected; first three ordering scenarios passed, then `locked_turn_update_before_deletion` failed with deadlock `40P01` at 2026-11-19 08:34:01 UTC | Owned disposable container/tmpfs removed; no persistent database used |
| `804bfda06989fc6e5662c49fd0989e4b4676cd67` runtime patch | Local Windows: protected `python backend/tests/run_poc_review.py test_poc_deletion_lifecycle` | All four mock lifecycle tests passed at the 2026-11-19 08:34:19 UTC checkpoint | Network/credential/dotenv access blocked; scratch removed; no external accounts/data |
| `804bfda06989fc6e5662c49fd0989e4b4676cd67` | Same disposable command; [run 44488864904](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864904) | Passed at 2026-11-19 08:36:11 UTC: 469/469 assertions, `beta_case_retention.sql`, `beta_source_note_cascade.sql`, `counseling_parent_scope.sql`, `session_input_deletion.sql`, and all five ordering scenarios listed below | Zero remaining synthetic rows; container/tmpfs removed and unique image cleanup succeeded; no deployment |
| `804bfda06989fc6e5662c49fd0989e4b4676cd67` | [Product CI 44488864839](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864839), [security CI 44488864876](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44488864876) | All jobs passed by the 2026-11-19 08:38 UTC checkpoint: backend smoke/regressions, PDF export, frontend workflow checks/build, security regressions and protected PoC suite | Ephemeral CI with synthetic configuration/mocks; no real data or deployment |

### PR #105 failure mechanism and correction

The initial `42501` was a fixture error: the synthetic bypass-RLS role had `SELECT` on `cases`, but the invoker parent guard's `FOR SHARE` also needs `UPDATE` privilege. `fc37ffe` adds that privilege only inside the rollback-scoped SQL test; production grants are unchanged. See the [PostgreSQL SELECT privilege contract](https://www.postgresql.org/docs/15/sql-select.html).

The next CI run reproduced a real lock inversion. Deletion locked the session and then waited for a transcript row already locked by an updater. That updater's trigger requested `FOR SHARE` on the session, completing a deadlock cycle. `804bfda` keeps the UPDATE ownership, immutable-scope and deletion-marker checks but removes its second parent lock: the already-locked child forces deletion to wait, and the unchanged scope keeps that row inside the eventual delete. INSERT still holds the session share lock until commit so an insert is either included in deletion or rejected after observing the permanent marker. RPC authentication, grants, RLS, rollback and retained-output behavior are unchanged. This follows PostgreSQL's [row-lock and deadlock semantics](https://www.postgresql.org/docs/15/explicit-locking.html).

The existing deterministic two-connection tests observed actual blocking PIDs and passed without swallowing deadlock errors: `inserts_before_deletion`, `deletion_before_turn_insert`, `deletion_before_window_insert`, `locked_turn_update_before_deletion`, and `locked_window_update_before_deletion`. Each checks the permanent marker, cleared input columns, absent transcript rows and unchanged confirmed note after both transactions finish.

Focused source review covered the two-file follow-up diff, supporting parent/transcript guards, RLS, deletion RPC and rollback/ordering tests; it found no additional authorization bypass in this correction. The optional security diff scanner rejected this worktree with `Review changes requires a non-bare Git worktree with a resolvable HEAD`; no scanner pass or independent human sign-off is claimed. Broader PR #104 contention and all installed-environment gates remain open. Deployment ID/URL for every entry above: **none**; main was not merged and no migration was applied to an existing database. The checklist-only follow-up preserves the tested runtime, configuration, migrations and test fixtures, so the evidence for `804bfda` remains applicable.

Independent review of the follow-up inspected both outcomes of the shared guard, history consumer, public-key selection, configured audio startup and non-PoC compatibility. No additional P0/P1 was found within that scope. Stale preparation tokens still require cancel/restart after an expiry/history change; this is a fail-closed UX limitation, not an authorization bypass.
