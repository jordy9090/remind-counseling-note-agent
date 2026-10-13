# Security stack integration and release

Status: released and verified within the boundaries below on October 14, 2026 KST. PR #47 is merged and the tested tree serves [remind.ai.kr](https://remind.ai.kr). Final evidence is maintained on `codex/security-release-evidence-20261014`; this documentation branch is not deployed.

## Scope and authorization

Integrate security PRs #37–#46, preserve their dependency order and commit history, fix reproduced integration blockers, and release through the existing Vercel Git integration. The user's October 13–14 release-owner instruction authorizes code-only main merges, production deployment, synthetic smoke checks and rollback. Earlier per-merge/deployment approval gates in historical progress entries are superseded for this release.

No database migration, RLS change, historical-record repair, retention-default change, new product feature, or paid inference is included. Seo-young's unpublished features are a later integration dependency, not a blocker for these independent fixes.

## Candidate and integration decisions

- Pre-release main: `afd0476bd82dd7809b96fcd64a044325db06e565`.
- Existing stack tip: `b959970632660c6fdacfabdae3ee5fca7de0febe` (#46).
- Integration branch: `codex/security-integration-20261013`.
- Tested candidate: `573797de589760771ea40ceccbddb3eca7e3248b`; merged main: `bfcdea73d84fb29e99820fa201f4e32d977b846c`. Both have tree `8dd9122b3993c36c4db95e9a22dd05b7d3fbf6b0`.
- Cumulative review covered the 26-file stack diff and affected callers. Existing sealed security reports remain unchanged; fresh integration review found a legacy-cache bypass and confirmed a pre-existing supervision update error.
- Use one cumulative PR to main with **Create a merge commit**. Its history already contains #37 → #38 → #39 → #40 → #41 → #42 → #43 → #44 → #45 → #46 in order. Do not squash/rebase the aggregate, force-push the stack, or deploy intermediate #42 without #46.

| Integration issue | Reproduction and correction |
| --- | --- |
| Legacy recomposition cache skipped retrieval masking | Both handlers accepted a valid pre-fix cached response containing a synthetic identity marker without invoking generation. Bump the cache compatibility version; test fresh regeneration followed by a normal hit. Old files remain untouched, so this is not a retention-policy change. |
| Supervision repeat-save returned HTTP 500 | The existing caller passed a filter as a positional argument to a keyword-only API. Correct the argument order and `query=` binding. Preserve owner credentials, selected note ID, persistence gates and original session notes. Three tests cover successful repeat-save, opt-outs and failed updates. |
| Existing frontend verification scripts described an older UI | Update assertions against actual callbacks and current navigation, preserving payload/storage checks. Browser grounding tests explicitly reject the ignored local live fixture and use the checked-in synthetic fixture. |
| Audio appeared applied but did not reach session input | The existing callback relied on a deferred React state updater assigning outer variables. Compute the shared projection first and guard completion with the existing uploaded-file URL lifetime. Independent review caught and resolved a candidate stale-response regression; deleted/replaced workspaces ignore delayed success/errors and completion uses the latest speaker roles. No request cancellation or new audio feature is introduced. |

## Validation ledger

All data are synthetic. Local Python validation disables dotenv loading, supplies a synthetic model key, forces stub defaults and rejects non-loopback sockets/DNS. Browser fixtures use loopback-only application/storage services. No hosted accounts or counseling rows were created.

| Check | Executed result | Limit |
| --- | --- | --- |
| Initial complete backend discovery | 292 tests passed, zero failures/errors/skips; zero external network attempts | Baseline stack tip before integration fixes |
| Cache fix | 13 related tests passed; valid legacy-cache regression failed on both hosts before the version change | Local actual HTTP handlers and mock generation |
| Supervision fix | 15 persistence workflow tests passed; repeat-save failed before the correction | Real service contract with in-memory PostgREST |
| Complete backend discovery after these fixes | 296 tests passed, zero failures/errors/skips; zero external network attempts | Includes 93 security tests; does not prove hosted RLS |
| PDF-required backend smoke | Passed: health, generation, draft save, recomposition, supervision, DOCX/PDF and uploads; Linux PDF job also passed before and after merge | Windows used the supported PDF fallback; Linux CI installed native WeasyPrint dependencies |
| Production Python version parity | Python 3.12.13: all 296 tests passed in 10.267 seconds; PDF-required smoke passed in 9.937 seconds; zero external attempts | Initial Windows hardlink installation left `jsonpointer` incomplete; copy-mode reinstall corrected the environment. The initial failed run is retained, not counted as passing |
| Candidate CI | Product run `38420257034`: full backend 296, PDF smoke + supervision 8, frontend nine scripts/build; Security run `38420257066`: 93 passed | Actual job logs inspected; hosted authenticated workflows remain unverified |
| Merged-main CI | Product run `38422031411`: backend 296 in 3.529 seconds, PDF smoke + supervision 8 in 0.644 seconds, frontend nine scripts + build in 3.59 seconds | Exact merged SHA, all three jobs succeeded; complete backend discovery includes security tests |
| Isolated PostgreSQL integration | 41/41 combined scenario groups passed at 2026-10-13 14:56:42–14:56:44 UTC | PostgreSQL 18.6/PGlite 0.5.9 WASM, synthetic auth claims; not hosted PostgREST/JWT or multi-connection parity |
| Production baseline boundary smoke | 12/12 passed: health 200, protected routes reject missing/invalid tokens with 401; 11 responses match the Supabase auth guard; no token reflection | Invalid bodies cannot invoke generation; no authenticated production happy path or paid call |
| Frontend local suites | All nine package verification scripts passed; actual audio callback covers nine scheduling/lifecycle combinations | Existing UI assertions were corrected without removing storage/authorization checks |
| Frontend build | TypeScript + Vite build passed on final guarded audio source in 28.73 seconds, ending 2026-10-13 15:10:04 UTC | Existing approximately 637 kB bundle-size advisory remains |
| Browser persistence | Passed in 19.81 seconds, ending 2026-10-13 15:09:54 UTC: upload/audio, generate, failed/duplicate save, payload projection, reload, edit/confirm/reconfirm, legacy/invalid data, responsive sizes and missing-token handling | Headless Edge, real local routes with synthetic in-memory Auth/PostgREST and stub generation |
| Browser grounding | Passed in 6.84 seconds: evidence states, missing/stale sources, document/supervision navigation and flag-off behavior; zero generation requests | Checked-in synthetic fixture only; unchanged by the later audio-only correction |

The ten migration file hashes and combined proposal hash `f5f280a025a0d1ff1a0da8ae0225b8e920b54ae297cdadc56d4b115bebe1d933` are unchanged. Memory databases were closed. Private executable SQL and scenario evidence remain outside this public repository.

Cleanup: local servers stopped and memory rows were discarded. Automatic approval review rejected removal of nine newly created temporary Edge profiles with `blocked by policy` and no detailed reason. No alternate deletion was attempted; exact paths are retained in the private local product ledger. No remote data requires cleanup.

## Production configuration and rollback

Read-only provider inspection identified project `prj_VjnlRAWy86RpMAyNrpHCivFfgDPf`, team `team_efBJ2tezYcCBpMVDEOJtpyoq`, Hobby plan, and previous healthy production `dpl_4GASoXeGR66hBL6FkAvz9s6Fa7Vv` at main `afd0476`, region `iad1`. Immediately before merge, the normal deployment listing showed READY and `isRollbackCandidate: true`. The same listing reconfirmed both after deployment, with this release immediately following it. The optional rollback-only listing returned 403; no Vercel CLI was installed for its suggested fallback. The normal deployment metadata is the evidence for eligibility; rollback execution permissions were not exercised.

Production metadata includes the public-key/URL configuration and provider key. No service-role key is listed; the tested user-JWT/public-key paths do not require adding one. Non-secret flags stored as Sensitive cannot be read back through the connector: `RUNTIME_ENVIRONMENT`, `ENABLE_REAL_USER_AUTH`, `ENABLE_PERSISTENCE`, `ENABLE_CASE_MEMORY`, `SAVE_ORIGINAL_INPUT`, `USE_STUB`. Authentication behavior was independently observed by the boundary smoke; other values remain unknown. No flags or credentials will be changed for this code release. Treat generation as potentially paid and do not invoke it in production without cost authorization.

On this plan, instant rollback is limited to the immediately preceding production deployment. Use one cumulative release and avoid redundant production deployments. [Vercel rollback documentation](https://vercel.com/docs/cli/rollback).

Rollback procedure:

1. On an authentication, isolation, critical-route or sensitive-output regression, roll back to `dpl_4GASoXeGR66hBL6FkAvz9s6Fa7Vv` using the confirmed project/team IDs.
2. Verify restored alias assignment, source SHA, health, authorization negatives and the failing representative route.
3. Record that rollback disables automatic production alias assignment; resume only through deliberate subsequent promotion.
4. If source rollback is needed, create a separate branch and `git revert -m 1 bfcdea73d84fb29e99820fa201f4e32d977b846c`, review/test, then merge the revert PR. Do not remove #46 alone while retaining #42's earlier collision algorithm.
5. No data rollback is required or authorized by this code-only release. Preserve the previous deployment and stack branches until verification ends.

## Exact release sequence

1. Freeze the integration commit; verify #46 is its ancestor, the working diff has no unreviewed source, and `supabase/migrations` is unchanged.
2. Fetch main again. If it moved, inspect overlap before integrating; do not restart unrelated passing tests automatically.
3. Require the cumulative PR's full backend/security, Linux PDF, frontend static checks/build and local synthetic browser workflows. Inspect actual results, not only the overall status badge.
4. Confirm the rollback target still serves production. Verify the Git deployment target is this project/main. No deployment hold is assumed: provider metadata did not expose that setting.
5. Merge the aggregate PR once with `merge_method=merge` and the exact expected head SHA. Verify the resulting main tree equals the tested candidate tree.
6. Follow the existing Git-triggered production build for that SHA; do not also start a manual deployment. Inspect main CI results and build readiness.
7. Verify actual deployment ID, source SHA, target, READY status, domain assignment, homepage/assets, health and protected-route negatives. Inspect only aggregate or synthetic-filtered runtime diagnostics.
8. Roll back promptly on a release regression. Record any unexecuted authenticated/model-backed production checks accurately.
9. Check #37–#46 once for indirect-merge status. If a PR remains open, first prove its exact head is contained in main, then close it as incorporated; do not merge it again.

## Remaining dependencies and exact next actions

- **Seo-young:** exact PR/SHA for guest summary, account handoff, autosave, de-identification controls and deletion UI. Validate those changes separately with `seoyoung-integration-checklist.md`; do not duplicate them.
- **Database:** local tests confirm parent/child and reference-integrity defects. Review-only proposals do not repair existing bad relationships or reserved keys. Deployment version/catalog, native isolated parity and owner-approved legacy handling/lock/validation/rollback plans are required before any remote policy change.
- **Production access:** provide an authorized confirmed synthetic identity (two identities for cross-user checks), scoped to this project, before testing hosted login/JWT validation, save/reload/export and cross-user isolation. Local browser tests use synthetic Auth/PostgREST substitutes; production authorization negatives do not establish those positive flows. Sensitive feature-flag values and provider/backup/telemetry settings remain incompletely observable.
- **Product/legal:** retention, deletion graph, report audiences, supplier contracts and operator access remain decisions; no compliance, E2EE or administrator-inaccessibility claim is made.
- **Known baseline behavior:** the Vercel supervision wrapper does not implement the FastAPI persistence behavior. This release corrects the existing repeat-update call only and does not add a second feature implementation.

No additional approval is needed for the completed code release. Further work requires: (1) Seo-young's exact PR/SHA for the separate feature integration; (2) an authorized synthetic production identity and scoped configuration visibility for the remaining hosted checks; (3) approval of exact remote SQL, legacy-data handling, lock/validation/rollback plans before database changes; (4) product/legal decisions before retention or historical deletion changes; and (5) explicit cost authorization before live model/STT tests. Runtime flags were not changed to bypass any of these dependencies.

## Final release evidence

- [PR #47](https://github.com/jordy9090/remind-counseling-note-agent/pull/47) merged at 2026-10-13 15:26:05 UTC (October 14, 00:26:05 KST), with the expected-head guard and merge-commit method. Main SHA/tree match the candidate as above.
- All ten exact #37–#46 heads are ancestors of main. GitHub marked #37 indirectly merged; #38–#46 were closed as incorporated after ancestry verification. Their branches and dependency history were preserved; they were not merged a second time.
- [Main Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38422031411) passed. [Candidate Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38420257034) and [Security CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38420257066) also passed, with logs inspected.
- Candidate Preview `dpl_AJuqN5KQoJBzLDquzDV672sR41hc` was READY at candidate `573797d` before merge.
- Git-triggered production deployment: `dpl_FqEXtN3ZXa8CyjWtsd3WKn1atz3W`, source `bfcdea73d84fb29e99820fa201f4e32d977b846c`, target `production`, READY at 2026-10-13 15:30:12.992 UTC (October 14, 00:30:12.992 KST). Provider metadata confirms `remind.ai.kr` and `remind-counseling-note-agent.vercel.app` assigned to this deployment. No manual duplicate deployment was triggered.
- Post-release smoke completed by 15:30:55 UTC: health/authentication boundary **12/12 passed**, including 11 Supabase auth-guard responses, no synthetic-token reflection; homepage, current JS and CSS assets all **200** with correct content types. Production JS is `/assets/index-BbMiAsmW.js`, SHA-256 `2eba76ffb053a739e4706d384757d1275fb7c0a08d829f561b58e578d49eaaa5`.
- Deployment-scoped runtime queries from 15:30:12 UTC through approximately 15:31 UTC returned **zero error/fatal groups** and **zero groups matching the synthetic invalid token**. This short observation window is not a claim of universal absence of errors or leakage.
- Rollback was **not invoked**: executed checks found no release regression. The previous healthy deployment remains available according to normal provider metadata; the rollback-only list permission limitation is recorded above.
- No production counseling records, accounts, database policies, retention settings or environment variables were changed. No paid inference ran. Hosted authenticated happy paths remain explicitly unverified.

## Resumable checkpoint

The code-only release is complete. Resume from `codex/security-release-evidence-20261014` for these records, or create a new integration branch from the deployed main SHA for a new approved code task. The next feature-integration action is to obtain Seo-young's exact PR/SHA and compare it with `seoyoung-integration-checklist.md`. The next hosted-verification action is to supply the confirmed synthetic identities described above, then run only the missing authenticated save/reload/export and cross-user checks. Do not rerun completed suites solely because this session resumed.

Local private evidence remains in the sibling `security-integration-artifacts` directory: `release-checkpoint.json`, `production-boundaries-after.json`, `production-assets-after.json`, Python 3.12 logs and the combined PostgreSQL checkpoint. The separate product ledger records the nine retained temporary profile paths. They contain synthetic local test state; no hosted identity or data cleanup is pending.
