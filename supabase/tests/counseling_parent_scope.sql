-- Synthetic relationship/cleanup compatibility. Run only in the disposable fixture.
begin;
do $$
declare
    owner_a uuid := gen_random_uuid();
    case_a text := 'poc_parent_' || gen_random_uuid();
    case_b text := 'poc_parent_' || gen_random_uuid();
    session_a uuid := gen_random_uuid();
    session_b uuid := gen_random_uuid();
    note_a uuid := gen_random_uuid();
    note_b uuid := gen_random_uuid();
    note_linked uuid := gen_random_uuid();
    earlier_session uuid := gen_random_uuid();
    earlier_note uuid := gen_random_uuid();
begin
    insert into auth.users(id) values(owner_a);
    perform set_config('request.jwt.claim.sub', owner_a::text, true);
    perform set_config('request.jwt.claim.role', 'authenticated', true);
    set local role authenticated;
    insert into public.cases(id,user_id,counselor_id) values
      (case_a,owner_a::text,owner_a::text), (case_b,owner_a::text,owner_a::text);
    insert into public.sessions(id,case_id,user_id,session_number) values
      (session_a,case_a,owner_a::text,1), (session_b,case_b,owner_a::text,1);
    insert into public.generated_notes(id,case_id,session_id,user_id) values
      (note_a,case_a,session_a,owner_a::text), (note_b,case_b,session_b,owner_a::text);
    insert into public.sessions(id,case_id,user_id,session_number) values(earlier_session,case_a,owner_a::text,2);
    insert into public.generated_notes(id,case_id,session_id,user_id) values(earlier_note,case_a,earlier_session,owner_a::text);
    begin
        insert into public.verification_reports(case_id,session_id,user_id,note_id)
          values(case_a,session_a,owner_a::text,earlier_note);
        raise exception using errcode='P9001', message='Report references another session';
    exception when check_violation then null;
    end;
    -- A source note from another session of the same case remains legitimate.
    update public.generated_notes set source_note_id=earlier_note where id=note_a;
    begin
        update public.sessions set case_id=case_b,session_number=991 where id=session_a;
        raise exception using errcode='P9001', message='Session parent moved across cases';
    exception when check_violation then null;
    end;
    begin
        update public.generated_notes set case_id=case_b,session_id=session_b where id=note_a;
        raise exception using errcode='P9001', message='Note parent moved across cases';
    exception when check_violation then null;
    end;
    -- Owning both parents must not authorize mixing their case scopes.
    begin
        insert into public.evidence_items(case_id,session_id,user_id,source_text)
          values(case_a,session_b,owner_a::text,'Synthetic cross-case source');
        raise exception using errcode='P9001', message='Cross-case session link accepted';
    exception when check_violation then null;
    end;
    begin
        update public.generated_notes set source_note_id=note_b where id=note_a;
        raise exception using errcode='P9001', message='Cross-case note link accepted';
    exception when check_violation then null;
    end;
    -- Nullable parent links and legitimate same-case source links remain supported.
    insert into public.generated_notes(id,case_id,session_id,user_id,source_note_id)
      values(note_linked,case_a,session_a,owner_a::text,note_a);
    insert into public.evidence_items(case_id,user_id,source_text)
      values(case_a,owner_a::text,'Synthetic case-level source');
    delete from public.generated_notes where id=note_a;
    if not exists(select from public.generated_notes where id=note_linked and source_note_id is null) then
        raise exception 'Source deletion did not preserve the linked note';
    end if;
    insert into public.generated_notes(id,case_id,session_id,user_id) values(note_a,case_a,session_a,owner_a::text);
    update public.generated_notes set source_note_id=note_a where id=note_linked;
    delete from public.cases where id=case_a;
    if exists(select from public.sessions where case_id=case_a)
       or exists(select from public.generated_notes where case_id=case_a)
       or exists(select from public.evidence_items where case_id=case_a) then
        raise exception 'Case cascade cleanup failed';
    end if;
    if not exists(select from public.generated_notes where id=note_b) then
        raise exception 'Unrelated final note was lost';
    end if;
    reset role;
end $$;
rollback;
