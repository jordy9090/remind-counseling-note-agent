# AGENTS.md

These instructions apply to every coding agent working in this repository.

## Execution priorities

1. Preserve user data, authentication boundaries, and the currently healthy Production deployment.
2. Finish the requested deliverable with the smallest relevant change.
3. Minimize repeated tool calls, deployments, scans, and tests.
4. Keep the user informed when blocked or when scope must change.

## Scope freeze

- Translate the request into explicit completion criteria before editing.
- Once implementation begins, do not add refactors, cleanup, documentation, new features, or broader audits unless they are required for a completion criterion.
- When a defect is found, fix the narrowest cause and run the smallest test that proves the fix.
- Do not turn a focused deployment task into a repository-wide review.
- If a new issue is unrelated to the requested outcome, record it for follow-up and continue.

## Validation ledger

Maintain a short validation ledger in the working notes with:

- commit SHA
- deployment ID or URL
- environment
- exact test or check
- result and timestamp
- cleanup status for synthetic accounts and data

A passing result may be reused when the tested code, configuration, database policy, and deployment are unchanged.

Do not repeat a passing test because:

- the conversation was compacted
- the UI reconnected
- the agent resumed work
- a tool returned an empty progress message
- time passed without a relevant code or configuration change

After compaction or reconnection, reconstruct state from Git status, commit history, deployment status, PR status, and the validation ledger. Continue from the first unfinished criterion.

## Test selection

Use this order:

1. focused test for the changed behavior
2. affected subsystem regression tests
3. build or type check
4. one full E2E at the integration checkpoint
5. minimal Production smoke test after promotion

Run the full E2E once per candidate commit and deployment. Repeat it only when a change can affect that flow. State the precise invalidating change before rerunning.

A dependency, routing, authentication, RLS, persistence, or export change can justify the affected E2E segment. A comment, test expectation, documentation edit, unrelated upstream commit, reconnection, or merge with no conflict in the tested paths does not justify recreating accounts and repeating the complete E2E.

## Git and moving main

- At task start, fetch once and record the base SHA.
- Before opening or merging a PR, fetch again.
- If `main` moved, inspect the changed paths first.
- If upstream changes do not overlap the task or its tested runtime paths, update the branch and run only merge/conflict plus targeted regression checks.
- Do not restart the full validation sequence automatically.
- Avoid concurrent agents or workflows merging related branches into `main` during a release task. If concurrent changes are detected repeatedly, pause and report the competing PRs or SHAs.
- Never force-push or rewrite `main`.

## Deployments and external services

- Do not poll a deployment more frequently than needed. Use provider status and logs.
- A build wait is not permission to start extra reviews or scans.
- Keep the last healthy Production deployment available for rollback.
- Promote only the exact Preview commit that passed the required checks.
- Production smoke testing should cover health, authentication boundary, and one representative core flow unless the user asks for more.

## Authentication and synthetic E2E data

- Use synthetic data only.
- Prefer already-authorized administrator-created confirmed test users when email delivery limits would block E2E.
- Store credentials outside the repository and never print secrets, passwords, tokens, counseling text, or service-role keys.
- Use unique run IDs so retries cannot collide with prior data.
- Clean up synthetic rows, sessions, and Auth users once, then verify zero remaining records.
- Do not recreate accounts after cleanup unless a code or configuration change invalidated the authentication or isolation result.

## Security review

- Run the security scan once for the final security-sensitive diff.
- Re-run only if authentication, authorization, RLS, secret handling, upload parsing, logging, or export rendering changes afterward.
- If an optional scanner or integration is unavailable, perform a focused source review and continue. Do not block the release solely to connect an optional reporting integration.
- Do not scan generated lockfiles beyond confirming expected dependency changes unless dependency risk is part of the task.

## Time and loop limits

- If the same phase runs twice without a relevant change, stop and diagnose the loop.
- If a single command, deployment wait, planning state, or reconnection produces no new evidence for 10 minutes, report the exact blocker and next command instead of silently continuing.
- If two full E2E attempts fail for different test-harness reasons, validate the harness contract against the frontend request transformation before a third attempt.
- Do not spend tokens narrating every routine command. Report milestones, failures, scope changes, and final evidence.

## Release completion sequence

For a validated release, proceed directly:

1. confirm clean diff and no secrets or real data
2. push the tested commit
3. update or create one PR
4. check required CI
5. merge only when authorized
6. verify Production readiness
7. run the minimal Production smoke test
8. report commit, PR, deployment, tests, remaining failures, and rollback target

Do not repeat earlier completed steps unless a relevant change invalidated them.
