# Disposable PostgreSQL policy verification

This pack applies the repository's complete, unchanged migration sequence to a new PostgreSQL 15 database and executes synthetic SQL as `authenticated` and `anon`. It verifies PostgreSQL RLS, grants, constraints, triggers, and RPC behavior. It does not connect to a hosted project, sign in through Supabase Auth, validate JWT signatures, or prove that a deployed database matches these migrations.

The completion criterion is a successful CI run for the exact candidate commit with all policy probes passing, the existing retention procedure contract passing, and zero fixture rows after rollback. Static checks alone do not satisfy it. A failing forged-parent probe is a schema finding; do not weaken the expected denial to make CI green.

## Run

On any development machine, without installing dependencies:

```text
python backend/tests/run_poc_database.py --static
python -m unittest discover -s backend/tests/poc_database -p test_runner.py -v
```

On Linux with a local Docker daemon, or through the **Disposable PoC database contracts** GitHub Actions job:

```text
python3 backend/tests/run_poc_database.py --run-disposable
```

The runner builds a versioned test image, creates its own container, and removes that container and uniquely tagged image in `finally`. It never accepts a database URL, host, port, credential, project reference, existing container, or alternate migration directory. It addresses only the local Unix Docker socket, clears inherited Docker/PostgreSQL/cloud configuration, exposes no ports, disables container networking, and keeps PostgreSQL data on tmpfs. The Docker build context excludes everything except its Dockerfile. The initial database must match the hardcoded database/user/marker and have no user tables, custom schemas, or application roles before bootstrap or migration execution.

The sole image-build network activity retrieves the official PostgreSQL image, Debian/PGDG build packages, and the two pinned upstream extension sources. The database itself has no network. `pg_cron` is actually installed and both checked-in schedules are registered; background execution is disabled to avoid timer races. The retention SQL exercises the scheduled retention function body directly. This does not prove an external production scheduler is running.

## Coverage

| Boundary | Actual SQL checks |
| --- | --- |
| Twelve counseling tables | A and B positive INSERT/SELECT/UPDATE/DELETE; foreign SELECT/UPDATE/DELETE denial; owner reassignment and forged-owner INSERT denial; RLS enabled under non-superuser, non-bypass roles |
| Parent integrity | Foreign existing case references on children with case foreign keys; foreign session/note/source-note references on applicable children, on INSERT and UPDATE; unrelated unique conflicts are not accepted as proof of denial |
| Unsaved cases | Drafts, exports and retrieval logs retain their existing ability to store an owned row for an unsaved case ID; no new parent requirement is assumed |
| Vouchers | Own review acknowledgment, foreign snapshot source, forged recovery metadata, real delete/archive, owner-only history/restore and idempotent restore |
| Retrieval RPCs | Own result, spoofed owner filter, foreign case, anonymous execution for case memory and transcript windows |
| Shared KB | Authenticated read, denied writes, dense/hybrid RPC positives, anonymous denial |
| Private schemas/functions | Recovery and beta tables inaccessible to app roles; internal trigger/purge/retention functions not executable |
| Missing identity | No rows visible and inserts denied with an absent subject; spoofing a subject on `anon` does not grant access |
| Retention | Existing `supabase/tests/beta_case_retention.sql`, unchanged, including withdrawal, expiry, cross-case isolation, late-write denial and cleanup |
| Inventory/cleanup | New public tables fail the coverage inventory; both cron jobs registered; all counseling/KB/auth/private fixture rows zero after rollback |

Fixtures create database-only `auth.users(id)` rows with random IDs, then use the documented `SET LOCAL ROLE` and request-claim pattern. The bootstrap supplies only platform identity helpers and schema access; it does not supply application table grants, RLS policies, or parent-integrity constraints. The test helpers use `SECURITY INVOKER`. Failed attack probes roll back in a subtransaction, and the entire fixture rolls back even when policy expectations fail. Only test labels, Boolean results, SQLSTATE codes, migration hashes and counts are reported.

## Version provenance

Verified from public upstream sources on 2026-11-19:

| Dependency | Pinned source |
| --- | --- |
| PostgreSQL | `postgres:15.20-bookworm@sha256:8180c3e1b9b603d2988f937dfbe51008bad5c4b07c77f35119695c027a7315ab` (multi-platform manifest digest from the official registry) |
| pgvector | `v0.8.1`, commit `778dacf20c07caf904557a88705142631818d8cb` |
| pg_cron | `v1.6.7`, commit `465b38c737f584d520229f5a1d69d1d44649e4e5` |

Extension tag checkout must match the recorded commit before compilation. Debian build-tool packages follow the package repository for the pinned base image; this is an ephemeral test dependency, not an application runtime dependency.

References: [Supabase database testing](https://supabase.com/docs/guides/local-development/testing/overview), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [official PostgreSQL image metadata](https://github.com/docker-library/official-images/blob/master/library/postgres), [pgvector v0.8.1 build](https://github.com/pgvector/pgvector/blob/v0.8.1/Dockerfile), and [pg_cron v1.6.7 installation/configuration](https://github.com/citusdata/pg_cron/blob/v1.6.7/README.md).

For a release, retain the CI run URL, commit, reported migration hashes, policy result, retention result and cleanup count in the release validation ledger. Any live-environment authentication/role/schema-parity verification requires a separate authorized procedure; never point this disposable runner at that environment.
