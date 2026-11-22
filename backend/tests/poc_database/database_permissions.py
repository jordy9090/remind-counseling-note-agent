"""DB-only processing gates using synthetic roles, rows and concurrent sessions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from .contracts import TABLES, VECTOR, fixture, insert, key, probe_row, quote
from .parent_scope_concurrency import held_transaction


def build_permission_sql():
    owner, ids, rows = fixture()
    other = str(uuid4())
    case = ids["cases"]
    lines = ["begin;", Path(__file__).with_name("assertions.sql").read_text(encoding="utf-8"),
             f"insert into auth.users(id) values('{owner}'),('{other}');",
             f"select poc_permissions.authorize('{owner}','{case}');"]
    lines.extend(insert(t, rows[t]) + ";" for t in TABLES)
    # An archived document exercises definer-backed history and restoration too.
    lines += [f"delete from public.voucher_documents where id='{ids['voucher_documents']}';",
              "create temporary table permission_backup as select raw_app_meta_data from auth.users "
              f"where id='{owner}';",
              "create temporary table permission_event as select event_id from voucher_recovery.deletions "
              f"where case_id='{case}';", "grant select on permission_event to authenticated;"]
    lines.append(insert("voucher_documents", rows["voucher_documents"]) + ";")

    def count(sql, expected, label):
        lines.append(f"select poc_test.count_is({quote(sql)}, {expected}, {quote(label)});")

    def denied(sql, label):
        lines.append(f"select poc_test.denied({quote(sql)}, {quote(label)}, array['42501','23514','P0001']);")

    def actor(role="authenticated", subject=owner):
        lines.extend([f"set local request.jwt.claim.sub='{subject}';",
                      f"set local request.jwt.claim.role='{role}';", f"set local role {role};"])

    def matrix(label):
        actor()
        for table in TABLES:
            pred = f"{key(table)}={quote(ids[table])}"
            count(f"select count(*) from public.{table}", 0, label + ":" + table + ":select")
            count(f"with d as (update public.{table} set user_id=user_id where {pred} returning 1) select count(*) from d",
                  0, label + ":" + table + ":update")
            count(f"with d as (delete from public.{table} where {pred} returning 1) select count(*) from d",
                  0, label + ":" + table + ":delete")
            candidate = probe_row(table, rows[table])
            # INSERT/UPSERT into the already registered parent cannot gain access.
            if table == "cases":
                statement = insert(table, rows[table]) + " on conflict(id) do update set case_alias=excluded.case_alias"
            else:
                statement = insert(table, candidate)
            denied(statement, label + ":" + table + ":insert")
        for rpc, args in (("match_case_memory_chunks", f"{VECTOR},'{owner}','{case}',null,5"),
                          ("match_transcript_windows", f"{VECTOR},'{owner}','{case}',12")):
            count(f"select count(*) from public.{rpc}({args})", 0, label + ":" + rpc)
        for schema in ("public", "voucher_recovery"):
            history = "voucher_deletion_history" if schema == "public" else "history"
            restore = "restore_deleted_voucher" if schema == "public" else "restore"
            count(f"select jsonb_array_length({schema}.{history}('{case}'))", 0, label + ":" + schema + ":history")
            count(f"select count(*) from permission_event where {schema}.{restore}(event_id)->>'status'='missing'",
                  1, label + ":" + schema + ":restore")
        for schema in ("public", "session_input_lifecycle"):
            denied(f"select {schema}.delete_session_input('{ids['generated_notes']}')", label + ":" + schema + ":delete_source")
        lines.append("reset role;")

    mutations = {
        "missing": "'{}'::jsonb",
        "withdrawn": "jsonb_set(raw_app_meta_data, array['remind_processing_authorizations'," + quote(case) + ",'status'], '\"withdrawn\"')",
        "expired": "jsonb_set(raw_app_meta_data, array['remind_processing_authorizations'," + quote(case) + ",'expires_at'], '0')",
        "wrong_policy": "jsonb_set(raw_app_meta_data, array['remind_processing_authorizations'," + quote(case) + ",'policy_version'], '\"old\"')",
        "wrong_provider": "jsonb_set(raw_app_meta_data, array['remind_processing_authorizations'," + quote(case) + ",'permissions','storage'], '[\"other\"]')",
        "generation_only": "raw_app_meta_data #- array['remind_processing_authorizations'," + quote(case) + ",'permissions','storage']",
    }
    for label, mutation in mutations.items():
        lines.append(f"update auth.users set raw_app_meta_data={mutation}, raw_user_meta_data=(select raw_app_meta_data from permission_backup) where id='{owner}';")
        # A forged request GUC or cached JWT claim must not choose the DB policy.
        lines.append("set local app.processing_authorization_policy='synthetic-v1';")
        matrix(label)
        lines.append(f"update auth.users set raw_app_meta_data=(select raw_app_meta_data from permission_backup) where id='{owner}';")
    for label, statement, undo in (
        ("policy_missing", "delete from processing_authorization.policy", "insert into processing_authorization.policy values(true,'synthetic-v1')"),
        ("policy_replaced", "update processing_authorization.policy set version='synthetic-v2'", "update processing_authorization.policy set version='synthetic-v1'"),
        ("beta_withdrawn", f"update beta_retention.enrollments set withdrawn_at=clock_timestamp() where case_id='{case}'", f"update beta_retention.enrollments set withdrawn_at=null where case_id='{case}'"),
    ):
        lines.append(statement + ";")
        matrix(label)
        lines.append(undo + ";")
    # A copied permission under another authenticated user does not change ownership.
    lines.append(f"update auth.users set raw_app_meta_data=(select raw_app_meta_data from permission_backup) where id='{other}';")
    actor(subject=other)
    for table in TABLES:
        count(f"select count(*) from public.{table}", 0, "copied_foreign_grant:" + table)
    lines.append("reset role;")
    for role in ("anon", "service_role"):
        actor(role)
        for table in TABLES:
            for sql in (f"select * from public.{table}", f"truncate public.{table} cascade", insert(table, probe_row(table, rows[table]))):
                denied(sql, role + ":" + table + ":" + sql.split()[0])
        denied(f"select public.match_case_memory_chunks({VECTOR},'{owner}','{case}')", role + ":memory_rpc")
        denied(f"select public.match_transcript_windows({VECTOR},'{owner}','{case}')", role + ":transcript_rpc")
        lines.append("reset role;")
    actor()
    for signature, args in (("voucher_recovery.history_authorized_body", quote(case)),
                            ("voucher_recovery.restore_authorized_body", "gen_random_uuid()"),
                            ("session_input_lifecycle.delete_authorized_body", quote(ids["generated_notes"])),
                            ("processing_authorization.check_permission_unlocked", f"'{case}','synthetic-v1','storage','supabase'")):
        denied(f"select {signature}({args})", "private_body:" + signature)
    for table in TABLES:
        denied(f"truncate public.{table} cascade", "authenticated:no_truncate:" + table)
        count(f"select count(*) from public.{table}", 1, "restored_permission:read:" + table)
    lines += ["reset role;", "select json_build_object('label',label,'passed',passed,'diagnostic',diagnostic)::text from poc_test.results order by label;", "rollback;"]
    return "\n".join(lines) + "\n"


def verify_permission_concurrency(command, env, run, require_success):
    """Observe locks, not sleeps, for grant removal and policy replacement."""
    def query(sql, phase="Permission concurrency"):
        return require_success(run(command, env=env, sql=sql, timeout=30), phase)

    def wait_until(sql):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if query(sql) == "t":
                return
            time.sleep(0.05)
        raise RuntimeError("Expected permission transaction state not observed")

    passed = []
    owner, ids, rows = fixture()
    case = ids['cases']
    actor = f"set local role authenticated; set local request.jwt.claim.sub='{owner}';"
    query(f"begin; insert into auth.users(id) values('{owner}'); select poc_permissions.authorize('{owner}','{case}'); " +
          " ".join(insert(t, rows[t]) + ";" for t in TABLES) + " commit;")
    try:
        for allowed in (True, False):
            if not allowed:
                query(f"update auth.users set raw_app_meta_data='{{}}' where id='{owner}';")
            selects = [f"select count(*) from public.{t};" for t in TABLES]
            selects += [f"select count(*) from public.match_case_memory_chunks({VECTOR},'{owner}','{case}');",
                        f"select count(*) from public.match_transcript_windows({VECTOR},'{owner}','{case}');",
                        f"select public.case_processing_allowed('{case}','synthetic-v1','storage','supabase');",
                        f"select jsonb_array_length(public.voucher_deletion_history('{case}'));"]
            result = query("begin read only; " + actor + " ".join(selects) + " commit;", "Read-only Data API contract")
            expected = ["1" if allowed else "0"] * (len(TABLES) + 2) + ["t" if allowed else "f", "0"]
            if result.splitlines() != expected:
                raise RuntimeError("Read-only Data API permission matrix mismatch")
            passed.append("read_only:" + ("approved" if allowed else "revoked"))
    finally:
        query("begin; " + " ".join(f"delete from public.{t} where case_id='{case}';" for t in ('document_exports','counseling_drafts','retrieval_logs')) +
              f"delete from public.cases where id='{case}'; delete from beta_retention.enrollments where owner_id='{owner}'; "
              f"delete from auth.users where id='{owner}'; delete from processing_authorization.policy; commit;", "Read-only fixture cleanup")
    for authority in ("metadata", "policy", "beta", "combined"):
        for first in ("write", "revoke"):
            owner, ids, rows = fixture()
            case = ids["cases"]
            actor = f"set local role authenticated; set local request.jwt.claim.sub='{owner}';"
            holding, waiting = "permission_hold_" + uuid4().hex, "permission_wait_" + uuid4().hex
            query(f"begin; insert into auth.users(id) values('{owner}'); select poc_permissions.authorize('{owner}','{case}'); " +
                  insert("cases", rows["cases"]) + "; commit;")
            write = actor + "with d as (" + insert("document_exports", rows["document_exports"]) + " returning 1) select count(*) from d;"
            revoke = {"metadata": f"update auth.users set raw_app_meta_data='{{}}' where id='{owner}';",
                      "policy": "update processing_authorization.policy set version='revoked';",
                      "beta": f"update beta_retention.enrollments set withdrawn_at=clock_timestamp() where case_id='{case}';",
                      "combined": f"update auth.users set raw_app_meta_data='{{}}' where id='{owner}'; "
                                  f"update beta_retention.enrollments set withdrawn_at=clock_timestamp() where case_id='{case}';"}[authority]
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    # Expose the former INSERT-trigger inversion: hold Auth only,
                    # observe INSERT waiting on Auth, then acquire enrollment.
                    split_revoke = authority == "combined" and first == "revoke"
                    held_sql = write if first == "write" else (revoke.split(';')[0] + ';' if split_revoke else revoke)
                    with held_transaction(command, env, holding, held_sql) as holder:
                        wait_until(f"select exists(select from pg_stat_activity where application_name='{holding}' and state='idle in transaction');")
                        future = pool.submit(run, command, env=env,
                            sql=f"set application_name='{waiting}'; set statement_timeout='20s'; begin; " +
                                (revoke if first == "write" else write) + " commit;", timeout=30)
                        wait_until(f"select exists(select from pg_stat_activity w where application_name='{waiting}' and wait_event_type='Lock' "
                                   f"and exists(select from pg_stat_activity h where h.application_name='{holding}' and h.pid=any(pg_blocking_pids(w.pid))));")
                        finish_sql = revoke.split(';', 1)[1] if split_revoke else ""
                        out, err = holder.communicate(finish_sql + " commit;\n", timeout=25)
                        require_success(subprocess.CompletedProcess([], holder.returncode, out, err), "Finish permission holder")
                        result = future.result()
                        if first == "write":
                            require_success(result, "Revocation after committed write")
                        elif not result.returncode or not any(code in result.stderr for code in ("42501:", "P0001:")):
                            raise RuntimeError("Revocation-first write did not fail closed")
                if query(f"select count(*) from public.document_exports where case_id='{case}';") != ("1" if first == "write" else "0"):
                    raise RuntimeError("Unexpected committed row after permission race")
                # A later request cannot use a cached grant or see the earlier write.
                if query(f"begin; {actor} select count(*) from public.document_exports where case_id='{case}'; commit;") != "0":
                    raise RuntimeError("Revocation retry exposed rows")
                passed.append(authority + ":" + first + "_first")
            finally:
                query(f"begin; delete from public.document_exports where case_id='{case}'; delete from public.cases where id='{case}'; "
                      f"delete from beta_retention.enrollments where owner_id='{owner}'; delete from auth.users where id='{owner}'; "
                      "delete from processing_authorization.policy; commit;", "Permission fixture cleanup")
    return passed
