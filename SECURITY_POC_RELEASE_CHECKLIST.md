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

| Item | Evidence | Limits |
| --- | --- | --- |
| PR #100 baseline implementation and CI | [PR #100](https://github.com/jordy9090/remind-counseling-note-agent/pull/100); backend 25 and frontend 12 new mock regressions; [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942429), [security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44468942399) passed at `536d204` | Reused because unchanged; not proof of installed RLS or deployment settings |
| Original-input column and recompose cache guards | `poc_mode` overrides raw-input and cache flags; effective policy exposed to UI | Existing copies, drafts, sanitized narratives, excerpts and downloads remain sensitive |
| Guest handoff removed | Legacy pending summary discarded without display/import; signed-in save remains covered | Does not establish browser/device backup erasure |
| P0 follow-up: reviewed-history consumption | `398344b`: the graph now uses the same effective review predicate as receipt validation; a real graph-node/prompt regression proves counselor-masked history is not fetched again | Five synthetic history controls; no live model |
| P0 follow-up: shared identity disabled throughout PoC APIs | `398344b`: common dependency requires a verified bearer in PoC, authentication has no service-key fallback, startup rejects missing real-auth/public configuration | Six synthetic checks and independent review; actual participant roster remains blocked |

## Remaining: prioritized engineering work

| Priority / item | Evidence and action | Status / owner |
| --- | --- | --- |
| PR #100 follow-up integration | Verify CI for reviewed-history/identity corrections; both configuration templates now require real-user auth | Local green; CI pending |
| P1: reopened evidence projection | Historical failure still appears in `noteFromRecord`; retain only owned, validated saved excerpts for unchanged claims | Isolated reproduction/fix in progress; stacked branch `codex/poc-evidence-reopen` |
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

### PR #104 parent/child contention follow-up (2026-11-19)

Completion criteria: reproduce the remaining parent/child lock contention; make only the necessary correction; retain ownership, immutable scope, nullable-link and deletion behavior; pass the PR's disposable SQL, synthetic security and Product CI checks; record evidence and remaining issues here. No main merge, deployment, existing database access or real data is authorized.

Baseline: PR head `780465008f498b822aeb02cc97ac1be890bc8c80`, stacked base `e684f74a12b6e70e096d7b3520f0ed77dba205ad`, fetched main `f942db4ecb6e696d75022d3f01a52b8bf2a37cf0`. The development checkout remains untouched. The existing uncommitted parent-lock correction in the PR worktree is retained and reviewed. Windows has no Docker/PostgreSQL executable; real SQL execution uses the existing Linux CI runner with mock Auth roles/claims and a network-disabled, uniquely owned disposable PostgreSQL 15 container. No real Auth users, endpoints or credentials are used.

The unchanged baseline's [database run 44490958754](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/44490958754) reproduced **24 deadlocks (`40P01`) across 12 parent edges**: child-before-delete and parent/child content updates failed; all 12 delete-before-child controls and 469 role/RLS assertions passed. Logs confirm zero remaining synthetic rows and container removal at 08:51 UTC. This immutable red evidence is reused rather than rerunning the same baseline.

Correction: content-only updates still validate every parent through invoker/RLS reads, but do not reacquire parent row locks when all five relationship fields are unchanged. The already locked child forces parent cascade/SET NULL operations to wait, avoiding the inverted lock order. Inserts and relationship changes retain shared parent locks; session/note scope immutability and source-only detachment remain unchanged. The SQL contract now also rejects malformed legacy case/session/source-note links on content-only updates. The concurrency matrix adds insert-before-delete and delete-before-insert controls for every edge (60 scenarios total).

Both Vercel configuration roots disable Git deployments only for `codex/poc-parent-scope`, using the [documented branch setting](https://vercel.com/docs/project-configuration/git-configuration#git.deploymentenabled), so CI pushes do not create Preview deployments. No deployment/promotion command is part of this work.

| Code version | Environment / exact check | Result and UTC time | Deployment / cleanup |
| --- | --- | --- | --- |
| `7804650` | `python3 backend/tests/run_poc_database.py --run-disposable`, run 44490958754 | Reproduced: 24/36 concurrency failures (`40P01`); 469 SQL assertions passed, 2026-11-19 08:51 | No deployment for this check; zero fixture rows; container/tmpfs removed |
| `7804650` + candidate diff | Local `python backend/tests/run_poc_database.py --static`; `python -m unittest discover -s backend/tests/poc_database -p test_runner.py -v`; Python AST / Vercel JSON parse; `git diff --check` | Passed: 18 migrations, 469 assertions inventoried; 4 runner safety tests; syntax/config/diff checks, 2026-11-19 09:47 | No database or accounts created |
| Working candidate | Disposable SQL, synthetic security and Product CI | Pending push and execution | Deployment disabled for this branch |

Security review: one optional diff-scan attempt rejected this checkout with `Review changes requires a non-bare Git worktree with a resolvable HEAD.` No scanner pass is claimed. A separate focused source pass reviewed all six changed files and the parent FK/RLS/immutability contracts: the unlocked branch retains identical ownership/scope predicates, changes to any relationship field retain locking, the detachment exception cannot add a reference, test-only trigger bypasses roll back, and generated SQL has only authored identifiers/UUID fixtures. No additional issue was found within this correction; beta retention and privileged scope changes remain outside its proof. Review completed 2026-11-19 09:49 UTC.

Remaining issues and limits:

- The older beta retention guard also locks enrollment rows and rejects writes after withdrawal/expiry. Its `ON DELETE SET NULL` interaction for linked source notes can block beta erasure; ordinary `poc_parent_*` cases do not prove this beta path. It remains a separate release blocker, not silently fixed by this migration.
- Inserts and changed relationships deliberately retain locking. The matrix covers insert/delete races and unchanged-link updates, not every multi-row reparenting transaction or isolation level. No universal deadlock-free guarantee is claimed.
- Existing malformed rows are not rewritten; content updates fail closed until separately reviewed repair. Installed-policy parity, privileged operator behavior and all real-data/deployment gates above remain blocked.

### Earlier validation

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
