-- Disposable database only: fresh permissions and beta lifecycle must both allow.
begin;
create function pg_temp.check_permission(wanted boolean, label text) returns void
language plpgsql as $$
declare actual boolean;
begin
    select public.case_processing_allowed(current_setting('test.case'), 'synthetic-v1',
        'generate', 'openai') into actual;
    if actual is distinct from wanted then raise exception 'Permission failed: %', label; end if;
end $$;

do $$
declare
    owner_a uuid := gen_random_uuid();
    owner_b uuid := gen_random_uuid();
    receipt_id uuid := gen_random_uuid();
    case_key text;
    scope jsonb;
begin
    insert into auth.users(id) values(owner_a), (owner_b);
    case_key := beta_retention.enroll(receipt_id, owner_a, clock_timestamp() - interval '1 hour');
    perform set_config('test.case', case_key, true);
    perform set_config('test.owner_a', owner_a::text, true);
    perform set_config('test.owner_b', owner_b::text, true);
    scope := jsonb_build_object('status', 'active', 'policy_version', 'synthetic-v1',
        'receipt', receipt_id::text,
        'not_before', extract(epoch from clock_timestamp() - interval '1 minute'),
        'expires_at', extract(epoch from clock_timestamp() + interval '1 hour'),
        'permissions', jsonb_build_object('generate', jsonb_build_array('openai')));
    perform set_config('test.scope', scope::text, true);
    -- User metadata deliberately contains a valid-looking forged grant.
    update auth.users set raw_user_meta_data = jsonb_build_object(
        'remind_processing_authorizations', jsonb_build_object(case_key, scope));
end $$;

select set_config('request.jwt.claim.sub', current_setting('test.owner_a'), true);
set local role authenticated;
select pg_temp.check_permission(false, 'self-editable metadata is not authority');
reset role;
update auth.users set raw_app_meta_data = raw_user_meta_data where id=current_setting('test.owner_a')::uuid;
set local role authenticated;
select pg_temp.check_permission(true, 'approved text generation');
do $$ begin
    if public.case_processing_allowed(current_setting('test.case'), 'synthetic-v2', 'generate','openai')
       or public.case_processing_allowed(current_setting('test.case'), 'synthetic-v1', 'audio','openai')
       or public.case_processing_allowed(current_setting('test.case'), 'synthetic-v1', 'generate','clova')
       or public.case_processing_allowed('unregistered', 'synthetic-v1', 'generate','openai') then
        raise exception 'Policy, purpose, provider or case mismatch accepted';
    end if;
    begin
        perform 1 from beta_retention.enrollments;
        raise exception 'Private enrollment rows exposed';
    exception when insufficient_privilege then null; end;
end $$;
reset role;
select set_config('request.jwt.claim.sub', current_setting('test.owner_b'), true);
update auth.users set raw_app_meta_data = raw_user_meta_data where id=current_setting('test.owner_b')::uuid;
set local role authenticated;
select pg_temp.check_permission(false, 'copied foreign grant');
reset role;
select set_config('request.jwt.claim.sub', current_setting('test.owner_a'), true);

do $$
declare mutation jsonb;
begin
    foreach mutation in array array[
        '{"status":"withdrawn"}'::jsonb, '{"policy_version":"old"}'::jsonb,
        '{"receipt":"other"}'::jsonb, '{"expires_at":0}'::jsonb,
        '{"expires_at":"999999999999"}'::jsonb, '{"expires_at":999999999999}'::jsonb,
        '{"not_before":999999999999}'::jsonb, '{"permissions":{"generate":"openai"}}'::jsonb,
        '{"permissions":null}'::jsonb
    ] loop
        update auth.users set raw_app_meta_data = jsonb_build_object('remind_processing_authorizations',
            jsonb_build_object(current_setting('test.case'), current_setting('test.scope')::jsonb || mutation))
          where id=current_setting('test.owner_a')::uuid;
        set local role authenticated;
        perform pg_temp.check_permission(false, 'invalid or revoked permission');
        reset role;
    end loop;
end $$;
update auth.users set raw_app_meta_data = raw_user_meta_data where id=current_setting('test.owner_a')::uuid;
update beta_retention.enrollments set withdrawn_at=clock_timestamp() where case_id=current_setting('test.case');
set local role authenticated;
select pg_temp.check_permission(false, 'beta withdrawal with otherwise valid metadata');
reset role;
update beta_retention.enrollments set withdrawn_at=null, ends_at=clock_timestamp()-interval '1 second'
 where case_id=current_setting('test.case');
set local role authenticated;
select pg_temp.check_permission(false, 'beta expiry');
reset role;
set local role anon;
do $$ begin
    begin
        perform public.case_processing_allowed(current_setting('test.case'), 'synthetic-v1','generate','openai');
        raise exception 'Anonymous execution accepted';
    exception when insufficient_privilege then null; end;
end $$;
reset role;
rollback;
