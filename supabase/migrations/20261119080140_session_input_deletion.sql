-- Input deletion is permanent for this session. Notes, evidence and drafts remain.
create schema session_input_lifecycle;
revoke all on schema session_input_lifecycle from public, anon, authenticated, service_role;
grant usage on schema session_input_lifecycle to authenticated;

alter table public.sessions add column input_deleted_at timestamptz;
alter table public.sessions add constraint deleted_session_has_no_input
    check (input_deleted_at is null or (raw_input_text is null and sanitized_input_text is null));

create function session_input_lifecycle.guard_session_input_deletion() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    if tg_op = 'UPDATE' and old.input_deleted_at is not null
       and new.input_deleted_at is distinct from old.input_deleted_at then
        raise exception 'Session input deletion cannot be reset' using errcode = '23514';
    end if;
    if new.input_deleted_at is not null then
        if new.raw_input_text is not null or new.sanitized_input_text is not null then
            raise exception 'Session input was deleted; use a new session' using errcode = '23514';
        end if;
        if tg_op = 'UPDATE' and old.input_deleted_at is null then
            -- UPDATE already owns the parent row lock. A direct marker transition
            -- receives the same atomic derivative cleanup as the authenticated RPC.
            delete from public.transcript_windows where session_id = old.id;
            delete from public.transcript_turns where session_id = old.id;
        end if;
    end if;
    return new;
end $$;
revoke all on function session_input_lifecycle.guard_session_input_deletion() from public, anon, authenticated, service_role;
create trigger session_input_deletion_guard before insert or update on public.sessions
    for each row execute function session_input_lifecycle.guard_session_input_deletion();

create function session_input_lifecycle.guard_transcript_input_deletion() returns trigger
language plpgsql security definer set search_path = '' as $$
declare deleted_at timestamptz;
begin
    if tg_op = 'UPDATE' and
       row(new.user_id, new.counselor_id, new.case_id, new.session_id) is distinct from
       row(old.user_id, old.counselor_id, old.case_id, old.session_id) then
        raise exception 'Transcript scope cannot change' using errcode = '23514';
    end if;
    if tg_op = 'UPDATE' then
        -- UPDATE already locks this transcript row, so deletion must wait for it.
        -- Taking a parent lock here would invert deletion's session -> transcript
        -- order and deadlock. Keep the scope/marker check without another lock;
        -- the immutable scope prevents moving this row out of the pending delete.
        select s.input_deleted_at into deleted_at from public.sessions s
            where s.id = new.session_id and s.case_id = new.case_id
              and s.user_id = new.user_id and new.counselor_id = new.user_id;
    else
        -- INSERT has no existing child row to serialize with deletion. Hold SHARE
        -- until commit so deletion sees the insert, or the writer sees the marker.
        -- This also protects service-role writes that bypass RLS.
        select s.input_deleted_at into deleted_at from public.sessions s
            where s.id = new.session_id and s.case_id = new.case_id
              and s.user_id = new.user_id and new.counselor_id = new.user_id
            for share of s;
    end if;
    if not found or deleted_at is not null then
        raise exception 'Session input is unavailable' using errcode = '23514';
    end if;
    return new;
end $$;
revoke all on function session_input_lifecycle.guard_transcript_input_deletion() from public, anon, authenticated, service_role;
create trigger transcript_input_deletion_guard before insert or update on public.transcript_turns
    for each row execute function session_input_lifecycle.guard_transcript_input_deletion();
create trigger transcript_input_deletion_guard before insert or update on public.transcript_windows
    for each row execute function session_input_lifecycle.guard_transcript_input_deletion();

create function session_input_lifecycle.delete_session_input(p_note_id uuid) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
    owner_id text := auth.uid()::text;
    session_key uuid;
begin
    if owner_id is null then
        raise exception 'Authentication is required' using errcode = '42501';
    end if;
    select s.id into session_key
        from public.generated_notes n
        join public.sessions s on s.id = n.session_id and s.case_id = n.case_id
        join public.cases c on c.id = s.case_id
        where n.id = p_note_id and n.user_id = owner_id and s.user_id = owner_id
          and c.user_id = owner_id
          and (nullif(btrim(c.counselor_id), '') is null or btrim(c.counselor_id) = owner_id)
        for update of s;
    if not found then
        raise exception 'Session was not found inside the authenticated scope' using errcode = '42501';
    end if;
    update public.sessions
        set raw_input_text = null, sanitized_input_text = null,
            input_deleted_at = coalesce(input_deleted_at, clock_timestamp())
        where id = session_key;
    return session_key;
end $$;
revoke all on function session_input_lifecycle.delete_session_input(uuid) from public, anon, authenticated, service_role;
grant execute on function session_input_lifecycle.delete_session_input(uuid) to authenticated;

create function public.delete_session_input(p_note_id uuid) returns uuid
language sql security invoker set search_path = '' as $$
    select session_input_lifecycle.delete_session_input(p_note_id);
$$;
revoke all on function public.delete_session_input(uuid) from public, anon, authenticated, service_role;
grant execute on function public.delete_session_input(uuid) to authenticated;
