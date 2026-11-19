-- Disposable database only. All fixtures and injected failures roll back.
begin;
create temporary table poc_deletion_fixture as select
    gen_random_uuid() as owner_id, gen_random_uuid() as other_id,
    'poc_delete_' || gen_random_uuid()::text as case_id,
    gen_random_uuid() as session_id, gen_random_uuid() as active_session_id,
    gen_random_uuid() as note_id;
grant select on poc_deletion_fixture to authenticated, service_role, anon;
insert into auth.users(id) select owner_id from poc_deletion_fixture union all select other_id from poc_deletion_fixture;
insert into public.cases(id, user_id, counselor_id)
    select case_id, owner_id::text, owner_id::text from poc_deletion_fixture;
insert into public.sessions(id, case_id, user_id, session_number, raw_input_text, sanitized_input_text)
    select session_id, case_id, owner_id::text, 1, 'Synthetic raw input', 'Synthetic sanitized input' from poc_deletion_fixture
    union all select active_session_id, case_id, owner_id::text, 2, null, 'Synthetic new session' from poc_deletion_fixture;
insert into public.generated_notes(id, case_id, session_id, user_id, confirmation_status, confirmed_json)
    select note_id, case_id, session_id, owner_id::text, 'confirmed', '{"sections":{"session_content":"Synthetic final note"}}'
    from poc_deletion_fixture;
insert into public.evidence_items(case_id, session_id, user_id, source_text)
    select case_id, session_id, owner_id::text, 'Synthetic retained evidence' from poc_deletion_fixture;
insert into public.counseling_drafts(draft_id, case_id, user_id, data)
    select gen_random_uuid()::text, case_id, owner_id::text, '{"form":{"transcript_text":"Synthetic retained draft"}}'
    from poc_deletion_fixture;
insert into public.case_memory_chunks(case_id, session_id, user_id, counselor_id, source_note_id, field_type, chunk_text, source_ref)
    select case_id, session_id, owner_id::text, owner_id::text, note_id, 'session_content', 'Synthetic retained memory', 'synthetic-memory'
    from poc_deletion_fixture;
insert into public.transcript_turns(case_id, session_id, user_id, counselor_id, turn_index, speaker_role, sanitized_text)
    select case_id, session_id, owner_id::text, owner_id::text, 0, 'client', 'Synthetic transcript' from poc_deletion_fixture;
insert into public.transcript_windows(case_id, session_id, user_id, counselor_id, start_turn_index, end_turn_index, window_text, source_ref, content_hash)
    select case_id, session_id, owner_id::text, owner_id::text, 0, 0, 'Synthetic transcript', session_id::text, 'synthetic-hash'
    from poc_deletion_fixture;
create temporary table poc_retained_before as
    select 'generated_notes' as kind, to_jsonb(n) as value from public.generated_notes n where id=(select note_id from poc_deletion_fixture)
    union all select 'evidence_items', to_jsonb(e) from public.evidence_items e where case_id=(select case_id from poc_deletion_fixture)
    union all select 'case_memory_chunks', to_jsonb(m) from public.case_memory_chunks m where case_id=(select case_id from poc_deletion_fixture)
    union all select 'counseling_drafts', to_jsonb(d) from public.counseling_drafts d where case_id=(select case_id from poc_deletion_fixture);

create function pg_temp.expect_sqlstate(statement text, expected text) returns void language plpgsql as $$
begin
    begin
        execute statement;
    exception when others then
        if sqlstate = expected then return; end if;
        raise;
    end;
    raise exception 'Expected rejection with SQLSTATE %', expected;
end $$;

do $$ begin
    if has_function_privilege('anon', 'public.delete_session_input(uuid)', 'execute')
       or has_function_privilege('service_role', 'public.delete_session_input(uuid)', 'execute')
       or not has_function_privilege('authenticated', 'public.delete_session_input(uuid)', 'execute')
       or has_function_privilege('authenticated', 'session_input_lifecycle.guard_session_input_deletion()', 'execute')
       or has_function_privilege('authenticated', 'session_input_lifecycle.guard_transcript_input_deletion()', 'execute') then
        raise exception 'Unexpected deletion privileges';
    end if;
    perform set_config('request.jwt.claim.sub', (select other_id::text from poc_deletion_fixture), true);
end $$;
set local role authenticated;
select pg_temp.expect_sqlstate('select public.delete_session_input(note_id) from pg_temp.poc_deletion_fixture', '42501');
reset role;
set local role anon;
select pg_temp.expect_sqlstate('select public.delete_session_input(note_id) from pg_temp.poc_deletion_fixture', '42501');
reset role;
do $$ begin perform set_config('request.jwt.claim.sub', '', true); end $$;
set local role authenticated;
select pg_temp.expect_sqlstate('select public.delete_session_input(note_id) from pg_temp.poc_deletion_fixture', '42501');
reset role;
do $$ begin perform set_config('request.jwt.claim.sub', (select owner_id::text from poc_deletion_fixture), true); end $$;

-- Fail after windows are removed but before turns/input are removed. All steps must roll back.
create function pg_temp.fail_synthetic_turn_delete() returns trigger language plpgsql as $$
begin raise exception 'Synthetic deletion failure' using errcode='P9001'; end $$;
create trigger poc_fail_turn_delete before delete on public.transcript_turns
    for each row execute function pg_temp.fail_synthetic_turn_delete();
set local role authenticated;
select pg_temp.expect_sqlstate('select public.delete_session_input(note_id) from pg_temp.poc_deletion_fixture', 'P9001');
reset role;
drop trigger poc_fail_turn_delete on public.transcript_turns;
do $$ begin
    if not exists(select from public.transcript_windows where session_id=(select session_id from poc_deletion_fixture))
       or not exists(select from public.transcript_turns where session_id=(select session_id from poc_deletion_fixture))
       or not exists(select from public.sessions where id=(select session_id from poc_deletion_fixture)
                     and raw_input_text='Synthetic raw input' and sanitized_input_text='Synthetic sanitized input' and input_deleted_at is null) then
        raise exception 'Deletion failure left partial mutations';
    end if;
end $$;

set local role authenticated;
do $$
declare deleted_id uuid; marker timestamptz;
begin
    select public.delete_session_input(note_id) into deleted_id from poc_deletion_fixture;
    if deleted_id <> (select session_id from poc_deletion_fixture) then raise exception 'Incorrect deletion receipt'; end if;
    select input_deleted_at into marker from public.sessions where id=deleted_id;
    if marker is null then raise exception 'Missing deletion marker'; end if;
    perform public.delete_session_input(note_id) from poc_deletion_fixture;
    if marker is distinct from (select input_deleted_at from public.sessions where id=deleted_id) then
        raise exception 'Retry changed the deletion marker';
    end if;
end $$;
select pg_temp.expect_sqlstate('update public.sessions set input_deleted_at=null where id=(select session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('update public.sessions set sanitized_input_text=''Synthetic late source'' where id=(select session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('insert into public.transcript_turns(case_id,session_id,user_id,counselor_id,turn_index,speaker_role,sanitized_text)
    select case_id,session_id,owner_id::text,owner_id::text,0,''client'',''Synthetic late turn'' from pg_temp.poc_deletion_fixture', '23514');
select pg_temp.expect_sqlstate('insert into public.transcript_windows(case_id,session_id,user_id,counselor_id,start_turn_index,end_turn_index,window_text,source_ref,content_hash)
    select case_id,session_id,owner_id::text,owner_id::text,0,0,''Synthetic late window'',session_id::text,''synthetic'' from pg_temp.poc_deletion_fixture', '23514');

-- New sessions and ordinary updates still work. Existing derived rows cannot change scope.
insert into public.transcript_turns(case_id,session_id,user_id,counselor_id,turn_index,speaker_role,sanitized_text)
    select case_id,active_session_id,owner_id::text,owner_id::text,0,'client','Synthetic active turn' from poc_deletion_fixture;
insert into public.transcript_windows(case_id,session_id,user_id,counselor_id,start_turn_index,end_turn_index,window_text,source_ref,content_hash)
    select case_id,active_session_id,owner_id::text,owner_id::text,0,0,'Synthetic active window',active_session_id::text,'synthetic' from poc_deletion_fixture;
update public.transcript_turns set sanitized_text='Synthetic edited active turn' where session_id=(select active_session_id from poc_deletion_fixture);
update public.transcript_windows set embedding_model='synthetic-model' where session_id=(select active_session_id from poc_deletion_fixture);
select pg_temp.expect_sqlstate('update public.transcript_turns set session_id=(select session_id from pg_temp.poc_deletion_fixture)
    where session_id=(select active_session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('update public.transcript_windows set session_id=(select session_id from pg_temp.poc_deletion_fixture)
    where session_id=(select active_session_id from pg_temp.poc_deletion_fixture)', '23514');
reset role;

-- Give this synthetic bypass-RLS role table access to prove the trigger, not a missing grant, rejects it.
grant select, insert, update on public.sessions, public.transcript_turns, public.transcript_windows to service_role;
grant select on public.cases to service_role;
set local role service_role;
select pg_temp.expect_sqlstate('select public.delete_session_input(note_id) from pg_temp.poc_deletion_fixture', '42501');
select pg_temp.expect_sqlstate('update public.sessions set input_deleted_at=null where id=(select session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('update public.sessions set input_deleted_at=clock_timestamp() where id=(select session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('update public.sessions set raw_input_text=''Synthetic late raw'' where id=(select session_id from pg_temp.poc_deletion_fixture)', '23514');
select pg_temp.expect_sqlstate('insert into public.transcript_turns(case_id,session_id,user_id,counselor_id,turn_index,speaker_role,sanitized_text)
    select case_id,session_id,owner_id::text,owner_id::text,0,''client'',''Synthetic privileged turn'' from pg_temp.poc_deletion_fixture', '23514');
select pg_temp.expect_sqlstate('insert into public.transcript_windows(case_id,session_id,user_id,counselor_id,start_turn_index,end_turn_index,window_text,source_ref,content_hash)
    select case_id,session_id,owner_id::text,owner_id::text,0,0,''Synthetic privileged window'',session_id::text,''synthetic'' from pg_temp.poc_deletion_fixture', '23514');
reset role;

do $$
declare row_before record; present jsonb;
begin
    if exists(select from public.sessions where id=(select session_id from poc_deletion_fixture)
              and (raw_input_text is not null or sanitized_input_text is not null or input_deleted_at is null))
       or exists(select from public.transcript_turns where session_id=(select session_id from poc_deletion_fixture))
       or exists(select from public.transcript_windows where session_id=(select session_id from poc_deletion_fixture)) then
        raise exception 'Deleted source or transcript rows remain';
    end if;
    for row_before in select * from poc_retained_before loop
        execute format('select to_jsonb(t) from public.%I t where to_jsonb(t) = $1', row_before.kind)
            into present using row_before.value;
        if present is distinct from row_before.value then raise exception 'Retained content changed in %', row_before.kind; end if;
    end loop;
end $$;
rollback;
