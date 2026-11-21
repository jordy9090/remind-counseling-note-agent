"""Deterministic parent/child transactions in the runner's disposable database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import re
import subprocess
import time
from uuid import uuid4


# Exercise each parent edge guarded by counseling_integrity.check_parent_scope.
EDGES = (
    ("cases", "sessions"),
    ("cases", "generated_notes"),
    ("cases", "evidence_items"),
    ("cases", "verification_reports"),
    ("cases", "case_memory_chunks"),
    ("sessions", "generated_notes"),
    ("sessions", "evidence_items"),
    ("sessions", "verification_reports"),
    ("sessions", "case_memory_chunks"),
    ("generated_notes", "generated_notes"),
    ("generated_notes", "verification_reports"),
    ("generated_notes", "case_memory_chunks"),
)
EDITS = {
    "cases": "case_alias='Synthetic parent edit'",
    "sessions": "session_title='Synthetic edit'",
    "generated_notes": "draft_json='{\"synthetic\":\"edited\"}'::jsonb",
    "evidence_items": "source_text='Synthetic edit'",
    "verification_reports": "report_json='{\"synthetic\":\"edited\"}'::jsonb",
    "case_memory_chunks": "chunk_text='Synthetic edit'",
}


@contextmanager
def held_transaction(command, env, name, sql):
    with subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8") as process:
        try:
            process.stdin.write(
                f"set application_name='{name}'; set statement_timeout='20s'; "
                f"set idle_in_transaction_session_timeout='25s'; begin; {sql}\n"
            )
            process.stdin.flush()
            yield process
        finally:
            if process.poll() is None:
                process.kill()


def verify_parent_scope(command, env, run, require_success):
    """Report every ordering failure and clean each committed synthetic fixture."""
    def query(sql, phase="Parent scope concurrency", expected_error=None):
        result = run(command, env=env, sql=sql, timeout=30)
        if expected_error:
            if not result.returncode or not re.search(r"\bERROR:\s+" + expected_error + r":", result.stderr):
                raise RuntimeError("Expected SQLSTATE=" + expected_error + ": " + phase)
            return
        return require_success(result, phase)

    def wait_until(predicate, phase):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if query(f"select count(*) from pg_stat_activity where {predicate};") == "1":
                return
            time.sleep(0.05)
        raise RuntimeError("Expected lock state not observed: " + phase)

    passed, failed = [], []
    for parent, child in EDGES:
        for ordering in ("child_before_delete", "delete_before_child", "parent_child_updates",
                         "insert_before_delete", "delete_before_insert"):
            scenario = f"{parent}:{child}:{ordering}"
            owner, session, note, child_id, control_note = (str(uuid4()) for _ in range(5))
            case, control = "poc_parent_" + session, "poc_control_" + session
            holding, waiting = "poc_hold_" + uuid4().hex, "poc_wait_" + uuid4().hex
            actor = (f"set local role authenticated; set local request.jwt.claim.sub='{owner}'; "
                     "set local request.jwt.claim.role='authenticated'; ")
            parent_id = {"cases": case, "sessions": session, "generated_notes": note}[parent]
            linked_session = "null" if parent == "cases" else f"'{session}'"
            linked_note = f"'{note}'" if parent == "generated_notes" else "null"
            shared = f"'{child_id}','{case}','{owner}'"
            child_rows = {
                "sessions": "(id,case_id,user_id,session_number) "
                    f"values ({shared},2)",
                "generated_notes": "(id,case_id,user_id,session_id,source_note_id) "
                    f"values ({shared},{linked_session},{linked_note})",
                "evidence_items": "(id,case_id,user_id,session_id,source_text) "
                    f"values ({shared},{linked_session},'Synthetic evidence')",
                "verification_reports": "(id,case_id,user_id,session_id,note_id) "
                    f"values ({shared},{linked_session},{linked_note})",
                "case_memory_chunks": "(id,case_id,user_id,session_id,source_note_id,counselor_id,field_type,chunk_text,source_ref) "
                    f"values ({shared},{linked_session},{linked_note},'{owner}','session_content','Synthetic memory','synthetic:{child_id}')",
            }
            inserting = ordering in ("insert_before_delete", "delete_before_insert")
            insert_child = f"insert into public.{child} {child_rows[child]};"
            query(f"""begin;
                insert into auth.users(id) values ('{owner}');
                {actor}
                insert into public.cases(id,user_id,counselor_id) values
                  ('{case}','{owner}','{owner}'), ('{control}','{owner}','{owner}');
                insert into public.sessions(id,case_id,user_id,session_number)
                  values ('{session}','{case}','{owner}',1);
                insert into public.generated_notes(id,case_id,user_id,session_id)
                  values ('{note}','{case}','{owner}','{session}');
                insert into public.generated_notes(id,case_id,user_id,confirmed_json)
                  values ('{control_note}','{control}','{owner}','{{"synthetic":"retained"}}');
                {'' if inserting else insert_child}
                commit;
            """, "Create synthetic parent fixture")
            update_child = f"update public.{child} set {EDITS[child]} where id='{child_id}';"
            delete_parent = f"delete from public.{parent} where id='{parent_id}';"
            try:
                if ordering == "delete_before_insert":
                    first, second, final = delete_parent, insert_child, "select 1;"
                elif ordering == "insert_before_delete":
                    first, second, final = insert_child, delete_parent, "select 1;"
                elif ordering == "delete_before_child":
                    first, second, final = delete_parent, update_child, "select 1;"
                else:
                    first = f"select 1 from public.{child} where id='{child_id}' for update;"
                    final = update_child
                    second = delete_parent if ordering == "child_before_delete" else (
                        f"update public.{parent} set {EDITS[parent]} where id='{parent_id}'; "
                        # Touch the same child after updating its parent, without overwriting its content.
                        f"update public.{child} set created_at=created_at where id='{child_id}';"
                    )
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with held_transaction(command, env, holding, actor + first) as holder:
                        wait_until(f"application_name='{holding}' and state='idle in transaction'", scenario)
                        future = pool.submit(query,
                            f"set application_name='{waiting}'; set statement_timeout='20s'; "
                            f"begin; {actor}{second} commit;", scenario,
                            "23514" if ordering == "delete_before_insert" else None)
                        wait_until(f"application_name='{waiting}' and wait_event_type='Lock' and exists "
                            f"(select from pg_stat_activity h where h.application_name='{holding}' "
                            "and h.pid=any(pg_blocking_pids(pg_stat_activity.pid)))", scenario)
                        out, err = holder.communicate(final + " commit;\n", timeout=25)
                        require_success(subprocess.CompletedProcess([], holder.returncode, out, err), scenario)
                        future.result()

                retained_link = parent == child == "generated_notes"
                if ordering == "parent_child_updates":
                    expected = (f"exists(select from public.{parent} where id='{parent_id}' and {EDITS[parent]}) "
                                f"and exists(select from public.{child} where id='{child_id}' and {EDITS[child]})")
                else:
                    expected = f"not exists(select from public.{parent} where id='{parent_id}') and "
                    if retained_link and ordering != "delete_before_insert":
                        expected += (f"exists(select from public.{child} where id='{child_id}' "
                                     f"and source_note_id is null and "
                                     f"{EDITS[child] if not inserting else 'true'})")
                    else:
                        expected += f"not exists(select from public.{child} where id='{child_id}')"
                if query(f"""select ({expected}) and exists(select from public.generated_notes
                    where id='{control_note}' and confirmed_json='{{"synthetic":"retained"}}'::jsonb);""") != "t":
                    raise RuntimeError("Parent/child or unrelated-note invariant failed: " + scenario)
                passed.append(scenario)
                print("Parent concurrency passed: " + scenario, flush=True)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                # require_success exposes only the authored phase and SQLSTATE, never row content.
                failed.append({"scenario": scenario, "error": str(error)})
                print("Parent concurrency FAILED: " + scenario + ": " + str(error), flush=True)
            finally:
                query(f"begin; delete from public.cases where id in ('{case}','{control}'); "
                      f"delete from auth.users where id='{owner}'; commit;", "Parent fixture cleanup")
    return {"passed": passed, "failed": failed}
