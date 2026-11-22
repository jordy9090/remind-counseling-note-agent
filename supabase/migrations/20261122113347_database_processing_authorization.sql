-- Every application-accessible counseling row requires the same current grant.
-- An empty registry deliberately disables processing until operator approval.
create table processing_authorization.policy (
    singleton boolean primary key default true check (singleton),
    version text not null check (length(version) between 1 and 80)
);
alter table processing_authorization.policy enable row level security;
revoke all on processing_authorization.policy from public, anon, authenticated, service_role;

alter function processing_authorization.check_permission(text,text,text,text)
    rename to check_permission_unlocked;
revoke all on function processing_authorization.check_permission_unlocked(text,text,text,text)
    from public, anon, authenticated, service_role;

create function processing_authorization.check_permission(
    p_case_id text, p_policy_version text, p_purpose text, p_provider text
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare active_version text;
begin
    if auth.uid() is null then return false; end if;
    -- Hold the authority rows until transaction end. A committed revocation or
    -- policy replacement cannot race behind a successful DB permission check.
    if current_setting('transaction_read_only')::boolean then
        -- PostgREST GET/HEAD and STABLE RPCs run read-only transactions. Reads
        -- use the current statement snapshot; only writes need serialization.
        select version into active_version from processing_authorization.policy;
    else
        select version into active_version from processing_authorization.policy for share;
    end if;
    if active_version is null or active_version is distinct from p_policy_version then
        return false;
    end if;
    if not current_setting('transaction_read_only')::boolean then
        perform 1 from auth.users where id = auth.uid() for share;
        if not found then return false; end if;
        perform 1 from beta_retention.enrollments
          where case_id = p_case_id and owner_id = auth.uid() for share;
        if not found then return false; end if;
    end if;
    return processing_authorization.check_permission_unlocked(
        p_case_id, active_version, p_purpose, p_provider);
end $$;
revoke all on function processing_authorization.check_permission(text,text,text,text)
    from public, anon, authenticated, service_role;
grant execute on function processing_authorization.check_permission(text,text,text,text) to authenticated;

create function processing_authorization.database_allowed(p_case_id text) returns boolean
language plpgsql security definer set search_path = '' as $$
declare active_version text;
begin
    if auth.uid() is null then return false; end if;
    select version into active_version from processing_authorization.policy;
    return processing_authorization.check_permission(p_case_id, active_version, 'storage', 'supabase');
end $$;
revoke all on function processing_authorization.database_allowed(text)
    from public, anon, authenticated, service_role;
grant execute on function processing_authorization.database_allowed(text) to authenticated;

do $$
declare t text; case_column text;
begin
    foreach t in array array['cases','sessions','generated_notes','counseling_drafts',
        'case_memory_chunks','evidence_items','verification_reports','retrieval_logs',
        'document_exports','transcript_turns','transcript_windows','voucher_documents'] loop
        case_column := case when t = 'cases' then 'id' else 'case_id' end;
        -- No TRUNCATE/trigger privileges and no service-role Data API bypass.
        execute format('revoke all on public.%I from public, anon, authenticated, service_role', t);
        execute format('grant select, insert, update, delete on public.%I to authenticated', t);
        execute format('create policy current_processing_permission on public.%I
          as restrictive for all to authenticated
          using (processing_authorization.database_allowed(%I))
          with check (processing_authorization.database_allowed(%I))', t, case_column, case_column);
    end loop;
end $$;
revoke all on function public.match_case_memory_chunks(extensions.vector,text,text,text[],integer),
    public.match_transcript_windows(extensions.vector,text,text,integer) from public, anon, service_role;
grant execute on function public.match_case_memory_chunks(extensions.vector,text,text,text[],integer),
    public.match_transcript_windows(extensions.vector,text,text,integer) to authenticated;

-- Preserve the established implementations behind gated entry points. Revoke
-- direct execution of the renamed bodies, including private-schema SQL access.
alter function voucher_recovery.history(text) rename to history_authorized_body;
alter function voucher_recovery.restore(uuid) rename to restore_authorized_body;
alter function session_input_lifecycle.delete_session_input(uuid) rename to delete_authorized_body;
revoke all on function voucher_recovery.history_authorized_body(text),
    voucher_recovery.restore_authorized_body(uuid), session_input_lifecycle.delete_authorized_body(uuid)
    from public, anon, authenticated, service_role;

create function voucher_recovery.history(p_case text) returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
    if not processing_authorization.database_allowed(p_case) then return '[]'::jsonb; end if;
    return voucher_recovery.history_authorized_body(p_case);
end $$;

create function voucher_recovery.restore(p_event uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare case_key text;
begin
    -- Resolve scope without locking payload rows, then lock authority before
    -- the old implementation acquires case/archive/child locks.
    select case_id into case_key from voucher_recovery.deletions
      where event_id = p_event and owner_id = auth.uid();
    if not found or not processing_authorization.database_allowed(case_key) then
        return jsonb_build_object('status', 'missing');
    end if;
    return voucher_recovery.restore_authorized_body(p_event);
end $$;

create function session_input_lifecycle.delete_session_input(p_note_id uuid) returns uuid
language plpgsql security definer set search_path = '' as $$
declare case_key text;
begin
    select case_id into case_key from public.generated_notes
      where id = p_note_id and user_id = auth.uid()::text;
    if not found or not processing_authorization.database_allowed(case_key) then
        raise exception 'Session was not found inside the authenticated scope' using errcode = '42501';
    end if;
    return session_input_lifecycle.delete_authorized_body(p_note_id);
end $$;
revoke all on function voucher_recovery.history(text), voucher_recovery.restore(uuid),
    session_input_lifecycle.delete_session_input(uuid) from public, anon, authenticated, service_role;
grant execute on function voucher_recovery.history(text), voucher_recovery.restore(uuid),
    session_input_lifecycle.delete_session_input(uuid) to authenticated;

-- Operator-only enrollment, expiry/withdrawal erasure and retention jobs remain
-- callable only by their existing privileged roles; they must work after denial.
