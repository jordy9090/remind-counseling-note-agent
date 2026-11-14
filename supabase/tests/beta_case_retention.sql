begin;
-- This test creates only random, synthetic fixtures. Run inside a transaction and roll back.
do $test$
declare
    owner_id uuid := gen_random_uuid();
    other_id uuid := gen_random_uuid();
    receipt_id uuid := gen_random_uuid();
    expiry_receipt uuid := gen_random_uuid();
    test_signed_at timestamptz := clock_timestamp() - interval '10 minutes';
    k text;
    expiry_key text;
    other_key text := 'qa_retention_' || gen_random_uuid()::text;
    sess uuid := gen_random_uuid();
    note uuid := gen_random_uuid();
    t text;
    remaining bigint;
begin
    if exists(select from beta_retention.enrollments) then
        raise exception 'Use an empty test enrollment registry';
    end if;
    if has_schema_privilege('authenticated','beta_retention','usage') or
       has_function_privilege('anon','beta_retention.erase_due(uuid)','execute') then
        raise exception 'Unexpected application privileges';
    end if;
    insert into auth.users(id) values(owner_id),(other_id);
    k := beta_retention.enroll(receipt_id,owner_id,test_signed_at);
    if k <> beta_retention.enroll(receipt_id,owner_id,test_signed_at) then raise exception 'Retry failed'; end if;
    insert into public.cases(id,user_id) values(other_key,owner_id::text);
    begin
        perform beta_retention.withdraw(receipt_id,other_id);
        raise exception 'Test failed: wrong owner withdrew';
    exception when raise_exception then
        if sqlerrm <> 'Enrollment not found' then raise; end if;
    end;
    insert into public.sessions(id,user_id,case_id,session_number) values(sess,owner_id::text,k,1);
    insert into public.generated_notes(id,user_id,case_id,session_id) values(note,owner_id::text,k,sess);
    insert into public.evidence_items(user_id,case_id,session_id) values(owner_id::text,k,sess);
    insert into public.verification_reports(user_id,case_id,session_id) values(owner_id::text,k,sess);
    insert into public.case_memory_chunks(user_id,counselor_id,case_id,session_id,field_type,chunk_text,source_ref)
        values(owner_id::text,owner_id::text,k,sess,'session_content','synthetic','synthetic');
    insert into public.transcript_turns(user_id,counselor_id,case_id,session_id,turn_index,speaker_role,sanitized_text)
        values(owner_id::text,owner_id::text,k,sess,0,'client','synthetic');
    insert into public.transcript_windows(user_id,counselor_id,case_id,session_id,start_turn_index,end_turn_index,source_ref,content_hash,window_text)
        values(owner_id::text,owner_id::text,k,sess,0,0,'synthetic','synthetic','synthetic');
    insert into public.counseling_drafts(draft_id,case_id,user_id,data)
        values(gen_random_uuid()::text,k,owner_id::text,'{}'),(gen_random_uuid()::text,other_key,owner_id::text,'{}');
    insert into public.document_exports(user_id,case_id) values(owner_id::text,k);
    insert into public.retrieval_logs(user_id,case_id,retrieval_scope,query_hash) values(owner_id::text,k,'case_memory','synthetic');
    insert into public.voucher_documents(user_id,case_id,template,fingerprint,operation_key,request_hash,snapshot,privacy_status)
        values(owner_id,k,'form10','synthetic',gen_random_uuid(),'synthetic','{"sources":{}}','applied');
    insert into voucher_recovery.deletions(document_id,owner_id,case_id,template,deleted_at,expires_at,actor_role,backup,unavailable_sources)
        values(gen_random_uuid(),owner_id,k,'form10',now(),now()+interval '7 days','synthetic','{}','{}');
    perform beta_retention.withdraw(receipt_id,owner_id);
    perform beta_retention.withdraw(receipt_id,owner_id);
    if exists(select from public.cases where id=k) or exists(select from voucher_recovery.deletions where case_id=k) then
        raise exception 'Case or recovery copy remains';
    end if;
    foreach t in array array['sessions','generated_notes','evidence_items','verification_reports','case_memory_chunks',
        'transcript_turns','transcript_windows','counseling_drafts','document_exports','retrieval_logs','voucher_documents'] loop
        execute format('select count(*) from public.%I where case_id=$1',t) into remaining using k;
        if remaining<>0 then raise exception 'Case rows remain in %',t; end if;
    end loop;
    if not exists(select from public.counseling_drafts where case_id=other_key) then raise exception 'Other case affected'; end if;
    begin
        insert into public.document_exports(user_id,case_id) values(owner_id::text,k);
        raise exception 'Test failed: late export accepted';
    exception when raise_exception then
        if sqlerrm <> 'Beta case is unavailable' then raise; end if;
    end;
    expiry_key := beta_retention.enroll(expiry_receipt,other_id,test_signed_at);
    if not exists(select from beta_retention.enrollments where receipt=expiry_receipt and ends_at=test_signed_at + interval '168 hours') then
        raise exception 'Expiry deadline incorrect';
    end if;
    update beta_retention.enrollments set ends_at=clock_timestamp()-interval '1 minute' where receipt=expiry_receipt;
    perform beta_retention.erase_due(expiry_receipt);
    if exists(select from public.cases where id=expiry_key) then raise exception 'Expired case remains'; end if;
    if not exists(select from beta_retention.enrollments where receipt=expiry_receipt and erased_at is not null) then
        raise exception 'Receipt missing';
    end if;
    update beta_retention.enrollments set ends_at=clock_timestamp()-interval '1 year 1 day' where receipt=expiry_receipt;
    perform beta_retention.erase_due();
    if exists(select from beta_retention.enrollments where receipt=expiry_receipt) or
       not exists(select from beta_retention.enrollments where receipt=receipt_id) then raise exception 'Receipt retention error'; end if;
end $test$;
rollback;
