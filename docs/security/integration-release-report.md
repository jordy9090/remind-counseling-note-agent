# Security stack integration and release

Status: release candidate under validation. This report is updated with the actual merge and deployment evidence before completion.

## Scope and authorization

Integrate security PRs #37–#46, preserve their dependency order and commit history, fix reproduced integration blockers, and release through the existing Vercel Git integration. The user's October 13–14 release-owner instruction authorizes code-only main merges, production deployment, synthetic smoke checks and rollback. Earlier per-merge/deployment approval gates in historical progress entries are superseded for this release.

No database migration, RLS change, historical-record repair, retention-default change, new product feature, or paid inference is included. Seo-young's unpublished features are a later integration dependency, not a blocker for these independent fixes.

## Candidate and integration decisions

- Latest fetched main: `afd0476bd82dd7809b96fcd64a044325db06e565`.
- Existing stack tip: `b959970632660c6fdacfabdae3ee5fca7de0febe` (#46).
- Integration branch: `codex/security-integration-20261013`.
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
| PDF-required backend smoke | Passed: health, generation, draft save, recomposition, supervision, DOCX/PDF and uploads | Windows used the supported PDF fallback because native WeasyPrint libraries were absent; Linux native PDF CI remains a release gate |
| Isolated PostgreSQL integration | 41/41 combined scenario groups passed at 2026-10-13 14:56:42–14:56:44 UTC | PostgreSQL 18.6/PGlite 0.5.9 WASM, synthetic auth claims; not hosted PostgREST/JWT or multi-connection parity |
| Production baseline boundary smoke | 12/12 passed: health 200, protected routes reject missing/invalid tokens with 401; 11 responses match the Supabase auth guard; no token reflection | Invalid bodies cannot invoke generation; no authenticated production happy path or paid call |
| Frontend local suites | All nine package verification scripts passed; actual audio callback covers nine scheduling/lifecycle combinations | Existing UI assertions were corrected without removing storage/authorization checks |
| Frontend build | TypeScript + Vite build passed on final guarded audio source in 28.73 seconds, ending 2026-10-13 15:10:04 UTC | Existing approximately 637 kB bundle-size advisory remains |
| Browser persistence | Passed in 19.81 seconds, ending 2026-10-13 15:09:54 UTC: upload/audio, generate, failed/duplicate save, payload projection, reload, edit/confirm/reconfirm, legacy/invalid data, responsive sizes and missing-token handling | Headless Edge, real local routes with synthetic in-memory Auth/PostgREST and stub generation |
| Browser grounding | Passed in 6.84 seconds: evidence states, missing/stale sources, document/supervision navigation and flag-off behavior; zero generation requests | Checked-in synthetic fixture only; unchanged by the later audio-only correction |

The ten migration file hashes and combined proposal hash `f5f280a025a0d1ff1a0da8ae0225b8e920b54ae297cdadc56d4b115bebe1d933` are unchanged. Memory databases were closed. Private executable SQL and scenario evidence remain outside this public repository.

Cleanup: local servers stopped and memory rows were discarded. Automatic approval review rejected removal of nine newly created temporary Edge profiles with `blocked by policy` and no detailed reason. No alternate deletion was attempted; exact paths are retained in the private local product ledger. No remote data requires cleanup.

## Production configuration and rollback

Read-only provider inspection identified project `prj_VjnlRAWy86RpMAyNrpHCivFfgDPf`, team `team_efBJ2tezYcCBpMVDEOJtpyoq`, Hobby plan, and current production `dpl_4GASoXeGR66hBL6FkAvz9s6Fa7Vv` at main `afd0476`, region `iad1`, serving `remind.ai.kr`. The provider marked it as a rollback candidate. Reconfirm this target immediately before release.

Production metadata includes the public-key/URL configuration and provider key. No service-role key is listed; the tested user-JWT/public-key paths do not require adding one. Non-secret flags stored as Sensitive cannot be read back through the connector: `RUNTIME_ENVIRONMENT`, `ENABLE_REAL_USER_AUTH`, `ENABLE_PERSISTENCE`, `ENABLE_CASE_MEMORY`, `SAVE_ORIGINAL_INPUT`, `USE_STUB`. Authentication behavior was independently observed by the boundary smoke; other values remain unknown. No flags or credentials will be changed for this code release. Treat generation as potentially paid and do not invoke it in production without cost authorization.

On this plan, instant rollback is limited to the immediately preceding production deployment. Use one cumulative release and avoid redundant production deployments. [Vercel rollback documentation](https://vercel.com/docs/cli/rollback).

Rollback procedure:

1. On an authentication, isolation, critical-route or sensitive-output regression, roll back to `dpl_4GASoXeGR66hBL6FkAvz9s6Fa7Vv` using the confirmed project/team IDs.
2. Verify restored alias assignment, source SHA, health, authorization negatives and the failing representative route.
3. Record that rollback disables automatic production alias assignment; resume only through deliberate subsequent promotion.
4. If source rollback is needed, create a separate branch and `git revert -m 1 <integration-merge-sha>`, review/test, then merge the revert PR. Do not remove #46 alone while retaining #42's earlier collision algorithm.
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

## Remaining dependencies

- **Seo-young:** exact PR/SHA for guest summary, account handoff, autosave, de-identification controls and deletion UI. Validate those changes separately with `seoyoung-integration-checklist.md`; do not duplicate them.
- **Database:** local tests confirm parent/child and reference-integrity defects. Review-only proposals do not repair existing bad relationships or reserved keys. Deployment version/catalog, native isolated parity and owner-approved legacy handling/lock/validation/rollback plans are required before any remote policy change.
- **Production access:** no authorized synthetic authenticated identity has been identified. Login/save/reload/export happy paths on the hosted environment remain separate from local browser and authorization-negative evidence. Sensitive feature-flag values and provider/backup/telemetry settings remain incompletely observable.
- **Product/legal:** retention, deletion graph, report audiences, supplier contracts and operator access remain decisions; no compliance, E2EE or administrator-inaccessibility claim is made.
- **Known baseline behavior:** the Vercel supervision wrapper does not implement the FastAPI persistence behavior. This release corrects the existing repeat-update call only and does not add a second feature implementation.

## Final release evidence

Pending candidate freeze, frontend/browser results, cumulative PR CI, merge, deployment and post-release smoke. This section must contain actual SHAs and deployment identifiers before reporting a completed release.
