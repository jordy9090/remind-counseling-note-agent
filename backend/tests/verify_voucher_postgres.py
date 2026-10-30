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
    run(Path('supabase/migrations/20261030000100_voucher_documents.sql').read_text(encoding='utf-8'))
    run(f"insert into auth.users values ('{owner}'),('{other}'); insert into cases values ('test-case','{owner}'),('other-case','{other}'); insert into generated_notes values ('{note}','test-case','{owner}');")

    def actor(sql, user=owner):
        return f"set role authenticated; set request.jwt.claim.sub='{user}'; {sql}"

    def insert(doc=None, key=None, user=owner, case='test-case', sources=None, reviewed=False):
        doc, key = doc or str(uuid4()), key or str(uuid4())
        snapshot = json.dumps({'sources': {note: 'synthetic-hash'} if sources is None else sources})
        cols = ',reviewed_at,reviewed_by' if reviewed else ''
        vals = f",now(),'{user}'" if reviewed else ''
        return doc, f"insert into voucher_documents(id,case_id,user_id,operation_key,request_hash,template,snapshot,fingerprint,privacy_status{cols}) values ('{doc}','{case}','{user}','{key}','synthetic','form10','{snapshot}','synthetic','degraded'{vals});"

    doc, sql = insert()
    run(actor(sql))
    assert run(actor(f"select id from voucher_documents where id='{doc}'")) == doc
    assert run(actor('select count(*) from voucher_documents', other)) == '0'
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
    run(actor(insert(key=key, sources={})[1]))
    run(actor(insert(key=key, sources={})[1]), error='duplicate key')
    run(actor(f"delete from generated_notes where id='{note}'"))
    assert run(actor(f"select count(*) from voucher_documents where id='{doc}'")) == '0'
    run(actor("delete from cases where id='test-case'"))
    assert run('select count(*) from voucher_documents') == '0'
    run(f"insert into cases values ('test-case','{owner}'); insert into generated_notes values ('{note}','test-case','{owner}');")

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
    assert run('select (select count(*) from voucher_documents)+(select count(*) from cases)+(select count(*) from generated_notes)+(select count(*) from auth.users)') == '0'
    print('PASS: migration, owner CRUD/review, other-user/anonymous isolation, forged ownership/source/pre-review rejection, immutability, idempotency, source/case/account cascades, both insert/delete race orders; cleanup=0 rows')


if __name__ == '__main__':
    main()
