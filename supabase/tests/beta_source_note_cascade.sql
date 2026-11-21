-- Disposable database only. Exercise the source-note SET NULL cascade after beta end.
begin;
do $test$
declare
    owner_id uuid := gen_random_uuid();
    receipt_id uuid;
    case_key text;
    first_session uuid;
    later_session uuid;
    source_note uuid;
    derived_note uuid;
    ending text;
    control_case text := 'poc_beta_control_' || gen_random_uuid()::text;
begin
    if exists(select from beta_retention.enrollments) then
        raise exception 'Use an empty synthetic enrollment registry';
    end if;
    insert into auth.users(id) values(owner_id);
    insert into public.cases(id, user_id, counselor_id)
        values(control_case, owner_id::text, owner_id::text);
    foreach ending in array array['expiry', 'withdrawal'] loop
        receipt_id := gen_random_uuid();
        first_session := gen_random_uuid();
        later_session := gen_random_uuid();
        source_note := gen_random_uuid();
        derived_note := gen_random_uuid();
        case_key := beta_retention.enroll(receipt_id, owner_id, clock_timestamp() - interval '10 minutes');
        insert into public.sessions(id, case_id, user_id, session_number)
            values(first_session, case_key, owner_id::text, 1),
                  (later_session, case_key, owner_id::text, 2);
        insert into public.generated_notes(id, case_id, session_id, user_id, confirmed_json)
            values(source_note, case_key, first_session, owner_id::text,
                   '{"sections":{"session_content":"Synthetic source note"}}');
        insert into public.generated_notes(id, case_id, session_id, user_id, source_note_id, confirmed_json)
            values(derived_note, case_key, later_session, owner_id::text, source_note,
                   '{"sections":{"session_content":"Synthetic derived note"}}');
        if ending = 'expiry' then
            update beta_retention.enrollments set ends_at=clock_timestamp() - interval '1 minute'
                where receipt=receipt_id;
            perform beta_retention.erase_due(receipt_id);
        else
            perform beta_retention.withdraw(receipt_id, owner_id);
        end if;
        if exists(select from public.cases where id=case_key)
           or exists(select from public.sessions where case_id=case_key)
           or exists(select from public.generated_notes where case_id=case_key)
           or not exists(select from beta_retention.enrollments where receipt=receipt_id and erased_at is not null) then
            raise exception 'Source-note cascade blocked beta % erasure', ending;
        end if;
        begin
            insert into public.document_exports(user_id, case_id) values(owner_id::text, case_key);
            raise exception 'Late beta write unexpectedly succeeded';
        exception when raise_exception then
            if sqlerrm <> 'Beta case is unavailable' then raise; end if;
        end;
    end loop;
    if not exists(select from public.cases where id=control_case and user_id=owner_id::text) then
        raise exception 'Unrelated case was changed';
    end if;
end $test$;
rollback;
