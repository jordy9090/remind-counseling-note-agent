"""Run voucher migration contracts in a disposable, local PostgreSQL database.

Usage: python backend/tests/verify_voucher_postgres.py --psql PATH --port 55439
The database must be empty. This script never connects to a remote host.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--psql', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    command = [args.psql, '-X', '-h', '127.0.0.1', '-p', str(args.port), '-U', 'voucher_test', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-Atq']

    def run(sql, error=None):
        result = subprocess.run(command, input=sql, text=True, capture_output=True, encoding='utf-8', timeout=20)
        if error:
            assert result.returncode and error in result.stderr, result.stderr
        else:
            assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert run("select count(*) from information_schema.tables where table_schema='public'") == '0', 'Use an empty disposable cluster'
    owner, other, note = [str(uuid4()) for _ in range(3)]
    run("""
      create role anon; create role authenticated; create role service_role bypassrls;
      create schema auth;
      create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as
        $$select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid$$;
      grant usage on schema public, auth to anon, authenticated, service_role;
      create table public.cases(id text primary key, user_id text);
      create table public.generated_notes(id uuid primary key, case_id text references public.cases(id) on delete cascade, user_id text);
      alter table public.cases enable row level security;
      alter table public.generated_notes enable row level security;
      create policy user_owns_rows on public.cases for all to authenticated using (user_id=(select auth.uid())::text) with check (user_id=(select auth.uid())::text);
      create policy user_owns_rows on public.generated_notes for all to authenticated using (user_id=(select auth.uid())::text) with check (user_id=(select auth.uid())::text);
      grant select, insert, update, delete on public.cases, public.generated_notes to authenticated;
    """)
    migrations = Path('supabase/migrations')
    for migration in ('20261030000100_voucher_documents.sql', '20261101000100_voucher_form25.sql', '20261107102900_voucher_packet_insert_only.sql'):
        run((migrations / migration).read_text(encoding='utf-8'))
    run(f"insert into auth.users values ('{owner}'),('{other}'); insert into cases values ('test-case','{owner}'),('other-case','{other}'); insert into generated_notes values ('{note}','test-case','{owner}');")

    def actor(sql, user=owner):
        return f"set role authenticated; set request.jwt.claim.sub='{user}'; {sql}"

    def insert(doc=None, key=None, user=owner, case='test-case', sources=None, reviewed=False):
        doc, key = doc or str(uuid4()), key or str(uuid4())
        snapshot = json.dumps({'form': {'edition': 'ari-2026'}, 'sources': {note: 'synthetic-hash'} if sources is None else sources})
        cols = ',reviewed_at,reviewed_by' if reviewed else ''
        vals = f",now(),'{user}'" if reviewed else ''
        return doc, f"insert into voucher_documents(id,case_id,user_id,operation_key,request_hash,template,snapshot,fingerprint,privacy_status{cols}) values ('{doc}','{case}','{user}','{key}','synthetic','form10','{snapshot}','synthetic','degraded'{vals});"

    doc, sql = insert()
    run(actor(sql))
    other_note = str(uuid4())
    run(actor(f"insert into generated_notes values ('{other_note}','other-case','{other}');", other))
    other_doc, sql = insert(user=other, case='other-case', sources={other_note: 'synthetic-hash'})
    run(actor(sql, other))

    # Stage a valid legacy snapshot whose source was rekeyed before the migration.
    stale_id, replacement = str(uuid4()), str(uuid4())
    run(actor(f"insert into generated_notes values ('{stale_id}','other-case','{other}');", other))
    stale_doc, sql = insert(user=other, case='other-case', sources={stale_id: 'synthetic-hash'})
    run(actor(sql + f"update generated_notes set id='{replacement}' where id='{stale_id}';", other))

    # Model Supabase's direct role grants and bindings created before the fix.
    # Keep the temporary bindings in this connection across CREATE OR REPLACE.
    phases = ['grant execute on function public.delete_note_voucher_documents() to anon, authenticated;']
    for role in ('anon', 'authenticated'):
        phases.append(f"""
          set role {role};
          create temporary table forged_{role}(id uuid);
          insert into forged_{role} values ('{other_note}');
          create trigger forged after delete on forged_{role} for each row execute function public.delete_note_voucher_documents();
          reset role;
        """)
    phases.append((migrations / '20261110033500_restrict_voucher_note_cleanup.sql').read_text(encoding='utf-8'))
    recovery_sql = (migrations / '20261111044950_voucher_deletion_recovery.sql').read_text(encoding='utf-8')
    # pg_cron is a hosted extension; exercise its purge function locally and
    # verify job registration and execution in the deployment environment.
    phases.append(recovery_sql.split('-- Hosted scheduler', 1)[0])
    for role in ('anon', 'authenticated'):
        phases.append(f"""
          set role {role};
          do $$ begin
            if has_function_privilege(current_user, 'public.delete_note_voucher_documents()', 'EXECUTE') then
              raise exception 'cleanup function is still executable';
            end if;
            begin
              create trigger new_binding after delete on forged_{role} for each row execute function public.delete_note_voucher_documents();
              raise exception 'new binding allowed';
            exception when insufficient_privilege then null; end;
            begin
              delete from forged_{role};
              raise exception 'old binding allowed';
            exception when insufficient_privilege then null; end;
          end $$;
          reset role;
        """)
    run('\n'.join(phases))
    run(actor(f"update generated_notes set id='{uuid4()}' where id='{note}';"), error='ID cannot be changed')
    assert run(actor(f"update generated_notes set id=id, case_id=case_id where id='{note}' returning id;")) == note
    run(actor(f"insert into generated_notes values ('{stale_id}','test-case','{owner}'); delete from generated_notes where id='{stale_id}';"))
    assert run(actor(f"select id from voucher_documents where id='{stale_doc}'", other)) == stale_doc
    alias = '{' + note.upper().replace('-', '') + '}'
    alias_doc, sql = insert(sources={alias: 'synthetic-hash'})
    run(actor(sql))
    assert run(actor(f"select id from voucher_documents where id='{other_doc}'", other)) == other_doc
    assert run(actor(f"select id from voucher_documents where id='{doc}'")) == doc
    assert run(actor(f"select id from voucher_documents where id='{doc}'", other)) == ''
    run('set role anon; select * from voucher_documents;', error='permission denied')
    run(actor(insert(user=other, case='other-case', sources={})[1]), error='owner mismatch')
    run(actor(insert(case='other-case', sources={})[1]), error='owner mismatch')
    run(actor(insert(sources={str(uuid4()): 'missing'})[1]), error='source missing')
    run(actor(insert(reviewed=True)[1]), error='separate review')
    run(actor(f"update voucher_documents set snapshot='{{}}' where id='{doc}'"), error='immutable')
    run(actor(f"update voucher_documents set user_id='{other}' where id='{doc}'"), error='immutable')
    run(actor(f"update voucher_documents set reviewed_at=now(),reviewed_by='{other}' where id='{doc}'"), error='acknowledgement required')
    run(actor(f"update voucher_documents set reviewed_at=now(),reviewed_by='{owner}' where id='{doc}'"))
    assert run(actor(f"select reviewed_by from voucher_documents where id='{doc}'")) == owner
    run(actor(f"update voucher_documents set reviewed_at=now() where id='{doc}'"), error='immutable')
    assert run(actor(f"delete from voucher_documents where id='{doc}' returning id", other)) == ''
    assert run(actor(f"select id from voucher_documents where id='{doc}'")) == doc
    key = str(uuid4())
    unlinked, sql = insert(key=key, sources={})
    run(actor(sql))
    run(actor(insert(key=key, sources={})[1]), error='duplicate key')
    run(actor(f"delete from generated_notes where id='{note}'"))
    assert run(actor(f"select count(*) from voucher_documents where id='{doc}'")) == '0'
    assert run(actor(f"select count(*) from voucher_documents where id='{alias_doc}'")) == '0'
    assert run(actor(f"select id from voucher_documents where id='{unlinked}'")) == unlinked
    assert run(actor(f"select id from voucher_documents where id='{other_doc}'", other)) == other_doc
    run(actor("delete from cases where id='test-case'"))
    run(actor("delete from cases where id='other-case'", other))
    assert run('select count(*) from voucher_documents') == '0'
    run(f"insert into cases values ('test-case','{owner}'); insert into generated_notes values ('{note}','test-case','{owner}');")

    assert run('select count(*) from voucher_recovery.deletions') == '0'
    def restore(event, user=owner):
        return json.loads(run(actor(f"select public.restore_deleted_voucher('{event}')", user)))['status']

    def latest(document):
        return run(f"select event_id from voucher_recovery.deletions where document_id='{document}' order by deleted_at desc limit 1")

    doc, sql = insert()
    run(actor(sql))
    run(actor(f"delete from voucher_documents where id='{doc}'"))
    direct = latest(doc)
    entry = json.loads(run(actor("select voucher_deletion_history('test-case')")))[0]
    assert entry['reason'] == 'direct' and entry['deleted_by'] == owner and entry['can_restore'] and entry['by_me']
    assert not {'backup', 'snapshot', 'unavailable_sources'}.intersection(entry)
    assert run(actor("select voucher_deletion_history('test-case')", other)) == '[]'
    assert restore(direct, other) == 'missing'
    for sql in ("select * from voucher_recovery.deletions", "select * from voucher_recovery.source_context",
                "select voucher_recovery.purge_expired()"):
        run(actor(sql), error='permission denied')
    run(f"set role anon; select restore_deleted_voucher('{direct}')", error='permission denied')
    assert restore(direct) == 'ok' and restore(direct) == 'ok'
    assert run(f"select backup is null and restored_by='{owner}' from voucher_recovery.deletions where event_id='{direct}'") == 't'
    assert run(f"select detached_source_ids='{{}}' and reviewed_at is null from voucher_documents where id='{doc}'") == 't'
    archived, sql = insert()
    run(actor(sql + f"delete from voucher_documents where id='{archived}';"))
    run(actor(f"delete from generated_notes where id='{note}';"))
    cascaded = latest(doc)
    assert cascaded != direct and restore(direct) == 'consumed'
    assert run(f"select source_note_id='{note}' and deleted_by='{owner}' from voucher_recovery.deletions where event_id='{cascaded}'") == 't'
    run(actor(f"insert into generated_notes values ('{note}','test-case','{owner}')"))
    for event, document in ((cascaded, doc), (latest(archived), archived)):
        assert restore(event) == 'ok'
        assert run(f"select detached_source_ids=array['{note}'::uuid] from voucher_documents where id='{document}'") == 't'
    run(actor(f"delete from generated_notes where id='{note}';"))
    assert run(f"select count(*) from voucher_documents where id in ('{doc}','{archived}')") == '2'
    run(actor(f"update voucher_documents set detached_source_ids='{{}}' where id='{doc}'"), error='immutable')
    forged, sql = insert(sources={})
    run(actor(sql.replace("privacy_status)", "privacy_status,detached_source_ids)").replace("'degraded');", f"'degraded',array['{note}'::uuid]);")), error='row-level security')
    run(actor(f"delete from voucher_documents where id in ('{doc}','{archived}')"))
    expired = latest(doc)
    run(f"update voucher_recovery.deletions set expires_at=now()-interval '1 second' where event_id='{expired}'")
    assert restore(expired) == 'expired'
    run('select voucher_recovery.purge_expired()')
    assert run(f"select backup is null from voucher_recovery.deletions where event_id='{expired}'") == 't'
    run(f"update voucher_recovery.deletions set deleted_at=now()-interval '91 days' where event_id='{expired}'; select voucher_recovery.purge_expired();")
    assert restore(expired) == 'missing'
    assert run('select count(*) from voucher_recovery.source_context') == '0'
    # Someone who knows a deleted UUID can occupy it from another account.
    # The owner must recover without exposing or overwriting either document.
    run(f"insert into cases values ('other-case','{other}');")
    occupied, sql = insert(sources={})
    run(actor(sql + f"delete from voucher_documents where id='{occupied}';"))
    event = latest(occupied)
    run(actor(insert(doc=occupied, user=other, case='other-case', sources={})[1], other))
    restored = json.loads(run(actor(f"select restore_deleted_voucher('{event}')")))
    assert restored['status'] == 'ok' and restored['id'] != occupied
    assert json.loads(run(actor(f"select restore_deleted_voucher('{event}')"))) == restored
    assert run(actor(f"select id from voucher_documents where id='{occupied}'", other)) == occupied
    run(actor(f"delete from voucher_documents where id='{restored['id']}'"))
    run(actor("delete from cases where id='other-case'", other))
    run(actor(f"insert into generated_notes values ('{note}','test-case','{owner}');"))

    # First insert, then delete: deletion waits for the insert's source lock and
    # removes the newly committed snapshot as part of the same deletion.
    def transaction(sql):
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        proc.stdin.write(sql)
        proc.stdin.close()
        return proc

    def await_sleep():
        for _ in range(50):
            if run("select count(*) from pg_stat_activity where wait_event='PgSleep'") == '1':
                return
            time.sleep(0.1)
        raise AssertionError('Concurrent transaction did not reach synchronization point')

    doc, sql = insert()
    first = transaction(actor('begin;'+sql+'select pg_sleep(2); commit;'))
    await_sleep()
    run(actor(f"delete from generated_notes where id='{note}'"))
    assert first.wait(10) == 0, first.stderr.read()
    assert run('select count(*) from voucher_documents') == '0'

    # First delete, then insert: the blocked insert must fail after deletion.
    run(f"insert into generated_notes values ('{note}','test-case','{owner}');")
    first = transaction(actor(f"begin; delete from generated_notes where id='{note}'; select pg_sleep(2); commit;"))
    await_sleep()
    run(actor(insert()[1]), error='source missing')
    assert first.wait(10) == 0, first.stderr.read()
    run(actor(insert(sources={})[1]))
    run(f"delete from auth.users where id='{owner}'")
    assert run('select count(*) from voucher_documents') == '0'
    run('delete from cases; delete from auth.users;')
    assert run('select count(*) from voucher_recovery.deletions') == '0'
    assert run('select (select count(*) from voucher_documents)+(select count(*) from cases)+(select count(*) from generated_notes)+(select count(*) from auth.users)') == '0'
    print('PASS: migration, owner CRUD/review, role isolation, forged triggers denied, immutable source IDs, legacy ID reuse, UUID spellings, scoped cascades, both insert/delete race orders; cleanup=0 rows')


if __name__ == '__main__':
    main()
