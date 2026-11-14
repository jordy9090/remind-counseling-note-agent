-- Enrollment is explicit. Reserved, random identifiers keep the beta separate from existing cases.
create schema beta_retention;
revoke all on schema beta_retention from public, anon, authenticated, service_role;

create table beta_retention.enrollments (
    receipt uuid primary key,
    case_id text not null unique,
    owner_id uuid not null,
    signed_at timestamptz not null,
    ends_at timestamptz not null,
    withdrawn_at timestamptz,
    erased_at timestamptz,
    notified_at timestamptz,
    check (case_id = 'beta_rm_' || receipt::text)
);
revoke all on beta_retention.enrollments from public, anon, authenticated, service_role;
alter table beta_retention.enrollments enable row level security;

-- Prevent late independent inserts and concurrent writes from recreating expired records.
create function beta_retention.check_write() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
    case_key text;
    old_key text;
    scope beta_retention.enrollments;
begin
    if tg_table_name = 'cases' then
        case_key := new.id;
        if tg_op = 'UPDATE' then old_key := old.id; end if;
    else
        case_key := new.case_id;
        if tg_op = 'UPDATE' then old_key := old.case_id; end if;
    end if;
    if starts_with(old_key, 'beta_rm_') and old_key is distinct from case_key then
        raise exception 'A beta record cannot change case';
    end if;
    if starts_with(case_key, 'beta_rm_') then
        select * into scope from beta_retention.enrollments where case_id = case_key for share;
        if not found or scope.owner_id::text is distinct from new.user_id::text
           or scope.withdrawn_at is not null or scope.erased_at is not null or scope.ends_at <= clock_timestamp() then
            raise exception 'Beta case is unavailable';
        end if;
    end if;
    return new;
end $$;
revoke all on function beta_retention.check_write() from public, anon, authenticated, service_role;

do $$
declare t text;
begin
    foreach t in array array['cases','counseling_drafts','document_exports','retrieval_logs',
        'sessions','generated_notes','case_memory_chunks','evidence_items','verification_reports',
        'transcript_turns','transcript_windows','voucher_documents'] loop
        execute format('create trigger beta_case_write before insert or update on public.%I
                        for each row execute function beta_retention.check_write()', t);
    end loop;
end $$;

-- The operator keeps a random receipt with the signed form and reuses it on retries.
create function beta_retention.enroll(p_receipt uuid, p_owner uuid, p_signed_at timestamptz) returns text
language plpgsql set search_path = '' as $$
declare
    k text := 'beta_rm_' || p_receipt::text;
    previous beta_retention.enrollments;
begin
    if p_signed_at is null or p_signed_at > clock_timestamp()
       or p_signed_at + interval '168 hours' <= clock_timestamp() then
        raise exception 'Signature must be current';
    end if;
    perform 1 from auth.users where id = p_owner for key share;
    if not found then raise exception 'Counselor account not found'; end if;
    insert into beta_retention.enrollments(receipt,case_id,owner_id,signed_at,ends_at)
        values(p_receipt,k,p_owner,p_signed_at,p_signed_at + interval '168 hours')
        on conflict(receipt) do nothing;
    if not found then
        select * into strict previous from beta_retention.enrollments where receipt=p_receipt for share;
        if previous.owner_id is distinct from p_owner or previous.signed_at is distinct from p_signed_at
           or previous.withdrawn_at is not null or previous.erased_at is not null then
            raise exception 'Enrollment details do not match an active receipt';
        end if;
        return k;
    end if;
    -- A collision with any existing case aborts the whole enrollment.
    insert into public.cases(id,user_id,counselor_id,case_alias)
        values(k,p_owner::text,p_owner::text,'베타 ' || left(p_receipt::text,8));
    return k;
end $$;

create function beta_retention.erase_due(p_receipt uuid default null) returns void
language plpgsql set search_path = '' set timezone = 'Asia/Seoul' as $$
declare e beta_retention.enrollments;
begin
    for e in select * from beta_retention.enrollments
        where (p_receipt is null or receipt=p_receipt)
          and erased_at is null and (withdrawn_at is not null or ends_at <= clock_timestamp())
        order by ends_at, receipt for update skip locked loop
        -- These three tables lack a cascading case foreign key.
        delete from public.counseling_drafts where user_id=e.owner_id::text and case_id=e.case_id;
        delete from public.document_exports where user_id=e.owner_id::text and case_id=e.case_id;
        delete from public.retrieval_logs where user_id=e.owner_id::text and case_id=e.case_id;
        -- Cascades include transcript windows, vectors, voucher outputs and their recovery snapshots.
        delete from public.cases where id=e.case_id and user_id=e.owner_id::text;
        if exists(select from public.cases where id=e.case_id) then
            raise exception 'Case owner mismatch';
        end if;
        update beta_retention.enrollments set erased_at=clock_timestamp() where receipt=e.receipt;
    end loop;
    delete from beta_retention.enrollments where p_receipt is null and erased_at is not null
        and least(ends_at,withdrawn_at) + interval '1 year' <= clock_timestamp();
end $$;

create function beta_retention.withdraw(p_receipt uuid, p_owner uuid) returns void
language plpgsql set search_path = '' as $$
begin
    update beta_retention.enrollments set withdrawn_at=coalesce(withdrawn_at, clock_timestamp())
        where receipt=p_receipt and owner_id=p_owner and erased_at is null;
    if not found then
        if not exists(select from beta_retention.enrollments where receipt=p_receipt and owner_id=p_owner
                      and erased_at is not null) then raise exception 'Enrollment not found'; end if;
        return;
    end if;
    perform beta_retention.erase_due(p_receipt);
end $$;

revoke all on all functions in schema beta_retention from public, anon, authenticated, service_role;
select cron.schedule('remind-beta-retention', '* * * * *', 'select beta_retention.erase_due()');
