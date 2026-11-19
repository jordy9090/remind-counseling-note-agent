"""Run source migrations and synthetic SQL probes in a new local-only container.

No database URL, host, port, credentials, project, existing container, or migration
override is accepted. Linux Docker is required only for --run-disposable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from poc_database.contracts import PRIVATE_TABLES, PUBLIC_TABLES, TABLES, build_sql
from poc_database.parent_scope_concurrency import verify_parent_scope
from poc_database.beta_lifecycle import verify_beta_lifecycle


ROOT = Path(__file__).resolve().parents[2]
PACK = Path(__file__).with_name("poc_database")
DATABASE = "remind_poc_rls"
ADMIN = "remind_poc_ci"
MARKER = "synthetic-disposable-only"
DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def source_migrations():
    directory = ROOT / "supabase" / "migrations"
    migrations = sorted(directory.glob("*.sql"))
    if not migrations or any(path.is_symlink() or path.resolve().parent != directory.resolve()
                             or not re.fullmatch(r"\d{14}_[a-z0-9_]+\.sql", path.name) for path in migrations):
        raise RuntimeError("Expected only repository source migrations")
    return migrations


def clean_environment(scratch):
    # Exclude PG*, DOCKER_*, proxy, cloud, auth and tracing configuration.
    values = {name: os.environ[name] for name in ("PATH", "SystemRoot", "WINDIR") if name in os.environ}
    values.update(HOME=str(scratch), USERPROFILE=str(scratch), DOCKER_CONFIG=str(scratch),
                  LANG="C.UTF-8", LC_ALL="C.UTF-8")
    return values


def run(command, *, env, sql=None, timeout=90):
    return subprocess.run(command, input=sql, text=True, capture_output=True,
                          encoding="utf-8", env=env, timeout=timeout, check=False)


def require_success(result, phase):
    if result.returncode:
        # Inputs are synthetic, but do not print SQL bodies or arbitrary dependency errors.
        codes = sorted(set(re.findall(r"\b(?:ERROR|FATAL):\s+([A-Z0-9]{5}):", result.stderr)))
        suffix = "; SQLSTATE=" + ",".join(codes) if codes else ""
        raise RuntimeError(f"{phase} failed (exit {result.returncode}){suffix}")
    return result.stdout.strip()


def preflight_sql():
    return f"""select json_build_object(
      'database', current_database(), 'user', current_user,
      'marker', current_setting('remind.poc_fixture',true),
      'version', current_setting('server_version_num')::int,
      'user_tables', (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
        where c.relkind in ('r','p','v','m','f') and n.nspname not in ('pg_catalog','information_schema')
        and n.nspname not like 'pg_toast%' and n.nspname not like 'pg_temp%'),
      'custom_schemas', (select count(*) from pg_namespace where nspname not in ('public','pg_catalog','information_schema')
        and nspname not like 'pg_toast%' and nspname not like 'pg_temp%'),
      'fixture_roles', (select count(*) from pg_roles where rolname in ('anon','authenticated','service_role'))
    )::text;"""


def verify_preflight(value):
    expected = {"database": DATABASE, "user": ADMIN, "marker": MARKER,
                "user_tables": 0, "custom_schemas": 0, "fixture_roles": 0}
    if any(value.get(key) != expected_value for key, expected_value in expected.items()) \
            or not 150000 <= value.get("version", 0) < 160000:
        raise RuntimeError("Refusing a database that is not the new, empty PostgreSQL 15 fixture")


def cleanup_query():
    tables = [*("public." + table for table in PUBLIC_TABLES), *PRIVATE_TABLES, "auth.users"]
    return "select " + "+".join(f"(select count(*) from {table})" for table in tables) + ";"


def check_static():
    migrations = source_migrations()
    sql = build_sql()
    if not sql.startswith("begin;") or not sql.endswith("rollback;\n"):
        raise RuntimeError("The generated fixture must be transactional")
    if "security definer" in (PACK / "assertions.sql").read_text(encoding="utf-8").lower():
        raise RuntimeError("Test helpers must execute with the caller's RLS identity")
    for table in TABLES:
        for suffix in ("own_insert", "own_update", "own_delete", "foreign_select", "foreign_update", "foreign_delete", "owner_transfer"):
            if f"A:{table}:{suffix}" not in sql or f"B:{table}:{suffix}" not in sql:
                raise RuntimeError("Incomplete A/B SQL fixture inventory")
    print(json.dumps({"status": "static_only", "source_migrations": len(migrations),
                      "counseling_tables": len(TABLES), "private_tables": len(PRIVATE_TABLES),
                      "sql_assertions": sql.count("select poc_test."),
                      "database_execution": "not_run"}))


def run_disposable():
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Use the Linux CI job or a Linux host with a local Docker daemon")
    migrations = source_migrations()
    run_id = uuid4().hex
    image_tag = "remind-poc-rls:" + run_id
    container_id = None
    owned = False
    built = False
    cleanup_ok = False
    failures = []
    tests = 0
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in migrations}
    with tempfile.TemporaryDirectory(prefix="remind-poc-db-") as temporary:
        env = clean_environment(temporary)
        try:
            print("Building the disposable PostgreSQL 15 fixture with vector and cron", flush=True)
            require_success(run([*DOCKER, "build", "--tag", image_tag, str(PACK)], env=env, timeout=600), "Fixture image build")
            built = True
            container_id = require_success(run([*DOCKER, "run", "--detach", "--network", "none",
                "--name", "remind-poc-rls-" + run_id, "--label", "remind.poc.run=" + run_id,
                "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=512m",
                "--env", "POSTGRES_DB=" + DATABASE, "--env", "POSTGRES_USER=" + ADMIN,
                "--env", "POSTGRES_HOST_AUTH_METHOD=trust", image_tag,
                "postgres", "-c", "listen_addresses=", "-c", "shared_preload_libraries=pg_cron",
                "-c", "cron.database_name=" + DATABASE, "-c", "cron.launch_active_jobs=off",
                "-c", "remind.poc_fixture=" + MARKER], env=env), "Disposable database creation")
            if not re.fullmatch(r"[0-9a-f]{64}", container_id):
                raise RuntimeError("Unexpected disposable container identity")
            inspected = json.loads(require_success(run([*DOCKER, "inspect", container_id], env=env), "Container inspection"))[0]
            owned = inspected["Config"].get("Labels", {}).get("remind.poc.run") == run_id
            host = inspected["HostConfig"]
            if not owned or host["NetworkMode"] != "none" or host.get("PortBindings") \
                    or "/var/lib/postgresql/data" not in host.get("Tmpfs", {}):
                raise RuntimeError("Disposable container isolation contract failed")

            command = [*DOCKER, "exec", "-i", container_id, "psql", "-X", "-w", "-Atq",
                       "-h", "/var/run/postgresql", "-U", ADMIN, "-d", DATABASE,
                       "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose"]
            for _ in range(60):
                ready = run(command, env=env, sql="select 1;", timeout=5)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Disposable database did not become ready in 60 seconds")
            verify_preflight(json.loads(require_success(run(command, env=env, sql=preflight_sql()), "Empty-database preflight")))
            require_success(run(command, env=env, sql=(PACK / "bootstrap.sql").read_text(encoding="utf-8")), "Synthetic identity bootstrap")
            for migration in migrations:
                # Apply the exact checked-in bytes, including real extension/scheduler declarations.
                require_success(run(command, env=env, sql=migration.read_text(encoding="utf-8-sig")), "Source migration " + migration.name)
            print("Source migrations applied; executing real role/RLS/function contracts", flush=True)
            output = require_success(run(command, env=env, sql=build_sql(), timeout=120), "SQL policy contracts")
            results = [json.loads(line) for line in output.splitlines() if line.strip()]
            tests = len(results)
            if tests == 0:
                raise RuntimeError("The SQL contract returned no test evidence")
            failures = [item for item in results if item.get("passed") is not True]
            # Every checked-in SQL contract owns a rollback transaction in this empty fixture.
            contracts = sorted((ROOT / "supabase" / "tests").glob("*.sql"))
            for contract in contracts:
                sql = contract.read_text(encoding="utf-8")
                if not re.search(r"(?im)^begin;", sql) or not sql.rstrip().lower().endswith("rollback;"):
                    raise RuntimeError("SQL contracts must use explicit rollback transactions")
                require_success(run(command, env=env, sql=sql), "Synthetic SQL contract " + contract.name)
            parent_concurrency = verify_parent_scope(command, env, run, require_success)
            beta_lifecycle = verify_beta_lifecycle(command, env, run, require_success)
            remaining = require_success(run(command, env=env, sql=cleanup_query()), "Synthetic row cleanup verification")
            cleanup_ok = remaining == "0"
            if not cleanup_ok:
                raise RuntimeError("Synthetic rows remain after transaction rollback")
            print(json.dumps({"status": "failed" if failures or parent_concurrency["failed"] or beta_lifecycle["failed"] else "passed", "sql_tests": tests,
                "failed_tests": failures, "retention_contract": "passed", "remaining_synthetic_rows": 0,
                "sql_contracts": [contract.name for contract in contracts],
                "parent_concurrency_contracts": parent_concurrency,
                "beta_lifecycle_contracts": beta_lifecycle,
                "migration_sha256": manifest}, indent=2))
        finally:
            if container_id and not owned:
                print("Cleanup NOT VERIFIED: the new container's ownership could not be confirmed; "
                      "no automatic deletion was attempted. Container=" + container_id, file=sys.stderr)
            if container_id and owned:
                removed = run([*DOCKER, "rm", "--force", "--volumes", container_id], env=env)
                if removed.returncode:
                    raise RuntimeError("Could not remove the owned disposable database container")
                print("Cleanup: owned disposable container and its tmpfs data removed", flush=True)
            if built and (container_id is None or owned):
                removed = run([*DOCKER, "image", "rm", image_tag], env=env)
                if removed.returncode:
                    raise RuntimeError("Could not remove the uniquely tagged fixture image")
            if container_id and not owned:
                raise RuntimeError("Cleanup unverified; the fixture container/image may remain and require inspection")
    return 1 if failures or parent_concurrency["failed"] or beta_lifecycle["failed"] or not cleanup_ok else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--static", action="store_true", help="Check generated fixture coverage without Docker or a database")
    mode.add_argument("--run-disposable", action="store_true", help="Create, verify and remove a new local-only Docker fixture")
    args = parser.parse_args()
    if args.static:
        check_static()
        return 0
    return run_disposable()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print("Database verification stopped: " + str(error), file=sys.stderr)
        sys.exit(2)
