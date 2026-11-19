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

## Completed

### Reopened evidence follow-up scope (2026-11-19)

- Reuse PR #101 at `574289f2bb036f00484d77fba58a7605c4ffa269` and its successful [Product CI run 44483484588](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44483484588), including 13 synthetic projection/rendering regressions. Base: PR #100 `d85a9a6`; fetched main remains `f942db4`. Keep PR #105's atomic deletion changes separate.
- Completion criteria: exercise the real note API routes with mocked storage/auth for edited claims, deleted input and synthetic A/B ownership; check saved-evidence rendering and empty restored inputs; fix only reproduced defects; obtain CI success and record remaining limits here.
- Use only protected local tests and GitHub CI. No operational server access, actual accounts/data, main merge or deployment. Block this branch's automatic Preview before pushing; preserve main's deployment behavior.

| Item | Evidence | Limits |
| --- | --- | --- |
| PR #100 baseline implementation and CI | [PR #100](https://github.com/jordy9090/remind-counseling-note-agent/pull/100); backend 25 and frontend 12 new mock regressions; [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942429), [security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942399) passed at `536d204` | Reused because unchanged; not proof of installed RLS or deployment settings |
| Original-input column and recompose cache guards | `poc_mode` overrides raw-input and cache flags; effective policy exposed to UI | Existing copies, drafts, sanitized narratives, excerpts and downloads remain sensitive |
| Guest handoff removed | Legacy pending summary discarded without display/import; signed-in save remains covered | Does not establish browser/device backup erasure |
| P0 follow-up: reviewed-history consumption | `398344b`: the graph now uses the same effective review predicate as receipt validation; a real graph-node/prompt regression proves counselor-masked history is not fetched again | Five synthetic history controls; no live model |
| P0 follow-up: shared identity disabled throughout PoC APIs | `398344b`: common dependency requires a verified bearer in PoC, authentication has no service-key fallback, startup rejects missing real-auth/public configuration | Six synthetic checks and independent review; actual participant roster remains blocked |
| PR #100 follow-up integration | Existing Product CI 44482299737 and security CI 44482299786 succeeded at `d85a9a6`; reused without rerunning | Complete on the PR branch; main merge remains unauthorized |
| P1: reopened evidence projection | PR #101: 14 synthetic projection/render checks plus two real-route/mock-transport regressions covering edited final text, deleted-input canaries and A/B account switching across all four read aliases | No new runtime defect reproduced. Original draft excerpts remain historical evidence; changed claims never regain a valid badge. Mock owner filtering does not certify installed RLS |

## Remaining: prioritized engineering work

| Priority / item | Evidence and action | Status / owner |
| --- | --- | --- |
| P1: residual retention and cleanup | Inspect deletion response semantics, partial failures, scratch cleanup and detector jobs against existing retention tools | Source review in progress |
| P1: tracing and diagnostics | Inspect graph/LLM callbacks in addition to application exception handlers; synthetic egress/log canaries | Source review in progress |
| Release verification pack | Safe preflight and disposable-database RLS/ownership procedure; no remote targets by default | In progress |

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

Independent review of the follow-up inspected both outcomes of the shared guard, history consumer, public-key selection, configured audio startup and non-PoC compatibility. No additional P0/P1 was found within that scope. Stale preparation tokens still require cancel/restart after an expiry/history change; this is a fail-closed UX limitation, not an authorization bypass.

### PR #101 reopened-evidence verification

**Repository-code evidence:** the original `574289f` implementation is unchanged. The new API regressions exercise actual FastAPI/Vercel route handlers with mocked authentication/storage: warm B's record, reject A's request for B's ID without its excerpt, then return only A's excerpt with `private, no-store`. After the mocked input-deletion route, all read aliases preserve edited final text, return no stored input or deleted-input-only canary, and keep only the saved excerpt. Removing that snapshot source leaves it absent; reopening never reads an evidence index or regenerates evidence. The frontend checks preserve all seven cleared input fields and render changed claims as needing re-review, missing/foreign sources as unavailable, and unchanged supported excerpts as reviewable.

**Operational-setting confirmation:** none performed or claimed. No operational server/DB access, accounts, merge or deployment. Existing CI and API mocks are not evidence of installed RLS, browser behavior against a deployed service, complete derivative erasure, or backup deletion. Session-input deletion intentionally retains summaries, evidence excerpts, case memory and temporary drafts. Atomic deletion/recreation races remain tracked separately in PR #105; the parent/beta work remains in PR #104.

**Preview guard:** both Vercel config locations now set only `git.deploymentEnabled["codex/*"] = false`, using [documented minimatch support](https://vercel.com/docs/project-configuration/git-configuration); unspecified branches including main retain the documented default. This covers matching branches when they contain this configuration; it does not change other PR branch contents or project-wide settings.

| Code version | Environment / exact check | Result and UTC time | Deployment / cleanup |
| --- | --- | --- | --- |
| `574289f` | Existing Product CI 44483484588 | Success reused; no unchanged build rerun locally | Historical CI only |
| `d73d348` | Protected runner `python backend/tests/run_poc_review.py --legacy test_security_access_boundaries.AccessBoundaryTests.test_reopened_evidence_is_owner_scoped_across_account_switches_and_aliases`; same runner with `test_security_access_boundaries.AccessBoundaryTests.test_reopen_after_input_deletion_preserves_edits_without_recreating_originals` | Both passed by 2026-11-19 10:30 UTC; initial deletion fixture omitted required `counselor_memo`, corrected before passing (test-fixture issue, no product defect) | In-memory mocks only; protected runner removed scratch; no accounts or persistent rows |
| `d73d348` | `cd frontend && node scripts/verify-poc-reopen.mjs` | 14/14 passed by 2026-11-19 10:30 UTC | Synthetic objects/static React rendering only; no network or stored data |
| `d73d348` | [Product CI 44506497560](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44506497560) and [security CI 44506497534](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44506497534) | Both completed successfully, confirmed 2026-11-19 10:33 UTC; backend regressions, PDF export, frontend workflows/build and protected PoC suite passed | Ephemeral CI only; Vercel deployment metadata returned zero deployments for this exact branch/SHA |

Focused source review checked record ownership chaining, original snapshot authority, edited-claim staleness, source identity filtering, restored-input fallback and account-keyed workspace remount. No additional defect was found in this scope. The optional scanner's previously recorded worktree limitation remains; no scanner pass is claimed. This local engineering item is complete on PR #101; operational gates and the separately tracked deletion/retention work remain open. Subsequent ledger-only edits do not invalidate the tested runtime/configuration.
