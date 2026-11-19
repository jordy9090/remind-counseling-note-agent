"""Prove transaction ordering in the disposable runner's own PostgreSQL instance."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import subprocess
import time
from uuid import uuid4


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


def finish(process, sql, require_success):
    out, err = process.communicate(sql + "; commit;\n", timeout=25)
    return require_success(subprocess.CompletedProcess([], process.returncode, out, err),
                           "Finish held deletion contract transaction")


def verify_session_deletion(command, env, run, require_success):
    """Use observed lock waits to order transactions without timing assumptions."""
    def query(sql, phase="Session deletion contract"):
        return require_success(run(command, env=env, sql=sql, timeout=30), phase)

    def wait_until(predicate, phase):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if query(f"select count(*) from pg_stat_activity where {predicate};") == "1":
                return
            time.sleep(0.05)
        raise RuntimeError(f"PostgreSQL did not reach the expected lock state: {phase}")

    scenarios = (
        "inserts_before_deletion",
        "deletion_before_turn_insert",
        "deletion_before_window_insert",
        "locked_turn_update_before_deletion",
        "locked_window_update_before_deletion",
    )
    for scenario in scenarios:
        owner, session, note = (str(uuid4()) for _ in range(3))
        case = "poc_concurrency_" + session
        holding = "poc_hold_" + uuid4().hex
        waiting = "poc_wait_" + uuid4().hex
        actor = (f"set local role authenticated; set local request.jwt.claim.sub='{owner}'; "
                 "set local request.jwt.claim.role='authenticated'; ")
        scope = f"'{case}','{session}','{owner}','{owner}'"
        turn = ("insert into public.transcript_turns "
                "(case_id,session_id,user_id,counselor_id,turn_index,speaker_role,sanitized_text) "
                f"values ({scope},0,'client','Synthetic turn');")
        window = ("insert into public.transcript_windows "
                  "(case_id,session_id,user_id,counselor_id,start_turn_index,end_turn_index,"
                  "window_text,source_ref,content_hash) "
                  f"values ({scope},0,0,'Synthetic window','transcript:{session}:0-0','synthetic');")
        delete = f"select public.delete_session_input('{note}');"
        query(f"""begin;
            insert into auth.users(id) values ('{owner}');
            insert into public.cases(id,user_id,counselor_id) values ('{case}','{owner}','{owner}');
            insert into public.sessions(id,case_id,user_id,session_number,raw_input_text,sanitized_input_text)
              values ('{session}','{case}','{owner}',1,'Synthetic raw input','Synthetic reviewed input');
            insert into public.generated_notes(id,case_id,session_id,user_id,confirmed_json)
              values ('{note}','{case}','{session}','{owner}','{{"final":"Synthetic final note"}}');
            commit;
        """)
        try:
            final_sql = "select 1"
            if scenario == "inserts_before_deletion":
                first, second = turn + window, delete
            elif scenario.startswith("deletion_before_"):
                first = delete
                insert = turn if scenario == "deletion_before_turn_insert" else window
                second = f"""do $$ begin
                    {insert}
                    raise exception 'A source row was recreated after deletion';
                    exception when check_violation then null;
                end $$;"""
            else:
                query("begin; " + actor + turn + window + " commit;")
                table, field = ("transcript_turns", "sanitized_text") if "turn" in scenario else (
                    "transcript_windows", "window_text"
                )
                first = f"select 1 from public.{table} where session_id='{session}' for update;"
                final_sql = f"update public.{table} set {field}='Synthetic edit' where session_id='{session}'"
                second = delete

            with ThreadPoolExecutor(max_workers=1) as pool:
                with held_transaction(command, env, holding, actor + first) as holder:
                    wait_until(f"application_name='{holding}' and state='idle in transaction'", scenario)
                    future = pool.submit(query,
                        f"set application_name='{waiting}'; set statement_timeout='20s'; "
                        f"begin; {actor}{second} commit;", scenario)
                    wait_until(
                        f"application_name='{waiting}' and wait_event_type='Lock' and exists "
                        f"(select from pg_stat_activity h where h.application_name='{holding}' "
                        "and h.pid=any(pg_blocking_pids(pg_stat_activity.pid)))",
                        scenario,
                    )
                    finish(holder, final_sql, require_success)
                    future.result()
            state = query(f"""select count(*) from public.sessions s
                join public.generated_notes n on n.id='{note}' and n.session_id=s.id
                where s.id='{session}' and s.input_deleted_at is not null
                and s.raw_input_text is null and s.sanitized_input_text is null
                and n.confirmed_json='{{"final":"Synthetic final note"}}'::jsonb
                and not exists(select from public.transcript_turns where session_id=s.id)
                and not exists(select from public.transcript_windows where session_id=s.id);
            """)
            if state != "1":
                raise RuntimeError(f"Deletion or retained-note invariant failed: {scenario}")
            print("Concurrency contract passed: " + scenario, flush=True)
        finally:
            query(f"begin; delete from public.cases where id='{case}'; "
                  f"delete from auth.users where id='{owner}'; commit;", "Concurrency fixture cleanup")
    return scenarios
