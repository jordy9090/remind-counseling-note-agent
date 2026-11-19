"""Synthetic expiry/withdrawal races in the runner's owned disposable database."""
from concurrent.futures import ThreadPoolExecutor
import re
import subprocess
import time
from uuid import uuid4

from .contracts import TABLES, fixture, insert, key, probe_row
from .parent_scope_concurrency import EDITS, held_transaction


BETA_EDITS = {
    **EDITS,
    "counseling_drafts": "data='{\"synthetic\":\"edited\"}'::jsonb",
    "document_exports": "title='Synthetic edit'",
    "retrieval_logs": "query_hash='synthetic-edit'",
    "transcript_turns": "sanitized_text='Synthetic edit'",
    "transcript_windows": "window_text='Synthetic edit'",
    "voucher_documents": "reviewed_at=now(),reviewed_by=user_id",
}


def verify_beta_lifecycle(command, env, run, require_success):
    def check(result, phase, denied=False):
        if denied:
            if not result.returncode or not re.search(r"\bERROR:\s+P0001:.*Beta case is unavailable", result.stderr):
                require_success(result, phase)
                raise RuntimeError("Expected unavailable beta rejection: " + phase)
            return
        return require_success(result, phase)

    def query(sql, phase="Beta lifecycle", denied=False):
        return check(run(command, env=env, sql=sql, timeout=30), phase, denied)

    def wait_until(predicate, phase):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if query(f"select ({predicate});") == "t":
                return
            time.sleep(0.05)
        raise RuntimeError("Expected transaction state not observed: " + phase)

    scenarios = [(mode, operation, None) for mode in ("expiry", "withdrawal")
                 for operation in ("cascade", "source_delete", "late_writes", "insert_before_retire")]
    scenarios += [("active", "source_delete", None)]
    scenarios += [(mode, "row_before_retire", table)
                  for mode in ("expiry", "withdrawal") for table in TABLES]
    passed, failed = [], []
    for mode, operation, table in scenarios:
        scenario = ":".join(filter(None, (mode, operation, table)))
        owner, ids, rows = fixture()
        receipt, linked, control_note = (str(uuid4()) for _ in range(3))
        case, control = "beta_rm_" + receipt, "poc_beta_control_" + receipt
        for row in rows.values():
            if "case_id" in row:
                row["case_id"] = case
        rows["cases"]["id"] = case
        actor = (f"set local role authenticated; set local request.jwt.claim.sub='{owner}'; "
                 "set local request.jwt.claim.role='authenticated'; ")
        expiry = f"update beta_retention.enrollments set ends_at=clock_timestamp()-interval '1 minute' where receipt='{receipt}';"
        withdrawn = f"update beta_retention.enrollments set withdrawn_at=clock_timestamp() where receipt='{receipt}';"
        erase = f"select beta_retention.erase_due('{receipt}');"
        withdraw = f"select beta_retention.withdraw('{receipt}','{owner}');"
        retire = erase if mode == "expiry" else withdraw
        late_insert = insert("document_exports", probe_row("document_exports", rows["document_exports"])) + ";"
        setup = " ".join(insert(name, rows[name]) + ";" for name in TABLES if name != "cases")
        query(f"""begin;
            insert into auth.users(id) values ('{owner}');
            select beta_retention.enroll('{receipt}','{owner}',clock_timestamp()-interval '10 minutes');
            {actor} {setup}
            -- A case-level child survives the session cascade long enough for SET NULL.
            insert into public.generated_notes(id,case_id,user_id,source_note_id,confirmed_json)
              values ('{linked}','{case}','{owner}','{ids['generated_notes']}','{{"synthetic":"retained"}}');
            insert into public.cases(id,user_id) values ('{control}','{owner}');
            insert into public.generated_notes(id,case_id,user_id,confirmed_json)
              values ('{control_note}','{control}','{owner}','{{"synthetic":"retained"}}');
            commit;""", "Create synthetic beta fixture")
        try:
            if mode == "expiry" and operation != "insert_before_retire":
                query(expiry)
            if mode == "withdrawal" and operation in ("source_delete", "late_writes"):
                query(withdrawn)
            if operation == "source_delete":
                query(f"begin; {actor} delete from public.generated_notes where id='{ids['generated_notes']}'; commit;", scenario)
                if query(f"select exists(select from public.generated_notes where id='{linked}' and source_note_id is null "
                         "and confirmed_json='{\"synthetic\":\"retained\"}'::jsonb);") != "t":
                    raise RuntimeError("Source deletion changed or lost the linked final note")
                query(retire, scenario)
            elif operation == "late_writes":
                for target in TABLES:
                    candidate = rows[target] if target == "cases" else probe_row(target, rows[target])
                    for statement in (insert(target, candidate),
                                      f"update public.{target} set {BETA_EDITS[target]} where {key(target)}='{ids[target] if target != 'cases' else case}'"):
                        query(f"begin; {actor} {statement}; commit;", scenario + ":" + target, denied=True)
                for change in ("source_note_id=null", "source_note_id=null,draft_json='{\"synthetic\":\"late\"}'"):
                    query(f"begin; {actor} update public.generated_notes set {change} where id='{linked}'; commit;", scenario, denied=True)
                query(retire, scenario)
            elif operation in ("row_before_retire", "insert_before_retire"):
                holding, waiting = "poc_beta_hold_" + uuid4().hex, "poc_beta_wait_" + uuid4().hex
                if operation == "insert_before_retire":
                    first, final = late_insert, "select 1;"
                    if mode == "expiry":
                        query(f"update beta_retention.enrollments set ends_at=clock_timestamp()+interval '3 seconds' where receipt='{receipt}';")
                else:
                    ident = case if table == "cases" else ids[table]
                    first = f"select 1 from public.{table} where {key(table)}='{ident}' for update;"
                    final = f"update public.{table} set {BETA_EDITS[table]} where {key(table)}='{ident}';"
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with held_transaction(command, env, holding, actor + first) as holder:
                        wait_until(f"exists(select from pg_stat_activity where application_name='{holding}' and state='idle in transaction')", scenario)
                        if operation == "insert_before_retire" and mode == "expiry":
                            wait_until(f"exists(select from beta_retention.enrollments where receipt='{receipt}' and ends_at<=clock_timestamp())", scenario)
                            query(retire, scenario)
                            if query(f"select exists(select from beta_retention.enrollments where receipt='{receipt}' and erased_at is null);") != "t":
                                raise RuntimeError("Locked enrollment was not deferred")
                            future = None
                        else:
                            future = pool.submit(query, f"set application_name='{waiting}'; set statement_timeout='20s'; begin; {retire} commit;", scenario)
                            wait_until(f"exists(select from pg_stat_activity w where application_name='{waiting}' and wait_event_type='Lock' "
                                       f"and exists(select from pg_stat_activity h where h.application_name='{holding}' and h.pid=any(pg_blocking_pids(w.pid))))", scenario)
                        out, err = holder.communicate(final + " commit;\n", timeout=25)
                        check(subprocess.CompletedProcess([], holder.returncode, out, err), scenario,
                              denied=mode == "expiry" and operation == "row_before_retire")
                        if future:
                            future.result()
                # Retries must finish SKIP LOCKED work and remain idempotent.
                query(retire, scenario)
            else:
                query(retire, scenario)
            query(retire, scenario)
            zero = " and ".join(f"not exists(select from public.{name} where {'id' if name == 'cases' else 'case_id'}='{case}')" for name in TABLES)
            if query(f"""select {zero}
                and not exists(select from voucher_recovery.deletions where case_id='{case}')
                and not exists(select from voucher_recovery.source_context where owner_id='{owner}')
                and exists(select from beta_retention.enrollments where receipt='{receipt}' and erased_at is not null)
                and exists(select from public.generated_notes where id='{control_note}' and confirmed_json='{{"synthetic":"retained"}}'::jsonb);""") != "t":
                raise RuntimeError("Erasure, receipt or unrelated final-note invariant failed")
            query(f"begin; {actor} {late_insert} commit;", scenario + ":no_resurrection", denied=True)
            passed.append(scenario)
            print("Beta lifecycle passed: " + scenario, flush=True)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            failed.append({"scenario": scenario, "error": str(error)})
            print("Beta lifecycle FAILED: " + scenario + ": " + str(error), flush=True)
        finally:
            # Remove the explicitly owned child first, even on the broken baseline.
            query(f"begin; delete from public.generated_notes where id='{linked}'; "
                  f"delete from public.cases where id in ('{case}','{control}'); "
                  f"delete from beta_retention.enrollments where receipt='{receipt}'; "
                  f"delete from auth.users where id='{owner}'; commit;", "Beta fixture cleanup")
    return {"passed": passed, "failed": failed}
