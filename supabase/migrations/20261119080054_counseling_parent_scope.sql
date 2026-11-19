-- Owner-only RLS does not establish ownership of a referenced parent row.
-- Keep the existing policies and reject inconsistent links before writes.
create schema counseling_integrity;
revoke all on schema counseling_integrity from public, anon, authenticated, service_role;

create function counseling_integrity.check_parent_scope() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare
    row_data jsonb := to_jsonb(new);
    parent_session uuid := nullif(row_data->>'session_id', '')::uuid;
    parent_note uuid;
    note_column text;
    lock_parents boolean := true;
begin
    -- The application updates content in place; it never moves saved parents.
    -- A later parent move would strand already-validated children in another scope.
    if tg_op = 'UPDATE' and tg_table_name in ('sessions', 'generated_notes')
       and (new.case_id is distinct from old.case_id or new.user_id is distinct from old.user_id
            or row_data->>'session_id' is distinct from to_jsonb(old)->>'session_id') then
        raise exception using errcode = '23514', message = 'Counseling parent scope is immutable';
    end if;
    -- ON DELETE SET NULL may detach a source while its whole case is cascading.
    -- Removing only this optional link cannot introduce a new parent reference.
    if tg_op = 'UPDATE' and tg_table_name = 'generated_notes'
       and row_data->>'source_note_id' is null and to_jsonb(old)->>'source_note_id' is not null
       and row_data - 'source_note_id' = to_jsonb(old) - 'source_note_id' then
        return new;
    end if;
    if tg_op = 'UPDATE' then
        lock_parents := row(row_data->>'user_id', row_data->>'case_id',
                            row_data->>'session_id', row_data->>'note_id', row_data->>'source_note_id')
            is distinct from row(old.user_id, old.case_id, to_jsonb(old)->>'session_id',
                                 to_jsonb(old)->>'note_id', to_jsonb(old)->>'source_note_id');
    end if;
    -- An unchanged relationship is already protected by the child's row lock:
    -- parent deletion must cascade through it (or clear its source-note link).
    -- Locking the parent again would invert that deletion/update lock order.
    -- Still validate existing links, including malformed rows predating this guard.
    -- New or changed links retain the original shared-lock validation.
    if lock_parents then
        perform 1 from public.cases c
          where c.id = new.case_id and c.user_id = new.user_id for share;
    else
        perform 1 from public.cases c
          where c.id = new.case_id and c.user_id = new.user_id;
    end if;
    if not found then
        raise exception using errcode = '23514', message = 'Counseling parent scope mismatch';
    end if;
    if parent_session is not null then
        if lock_parents then
            perform 1 from public.sessions s
              where s.id = parent_session and s.case_id = new.case_id
                and s.user_id = new.user_id for share;
        else
            perform 1 from public.sessions s
              where s.id = parent_session and s.case_id = new.case_id
                and s.user_id = new.user_id;
        end if;
        if not found then
            raise exception using errcode = '23514', message = 'Counseling parent scope mismatch';
        end if;
    end if;
    foreach note_column in array array['note_id', 'source_note_id'] loop
        parent_note := nullif(row_data->>note_column, '')::uuid;
        if parent_note is not null then
            -- Source notes can come from earlier sessions of the same owned case.
            if lock_parents then
                perform 1 from public.generated_notes n
                  where n.id = parent_note and n.case_id = new.case_id
                    and n.user_id = new.user_id
                    and (note_column <> 'note_id' or parent_session is null or n.session_id = parent_session)
                  for share;
            else
                perform 1 from public.generated_notes n
                  where n.id = parent_note and n.case_id = new.case_id
                    and n.user_id = new.user_id
                    and (note_column <> 'note_id' or parent_session is null or n.session_id = parent_session);
            end if;
            if not found then
                raise exception using errcode = '23514', message = 'Counseling parent scope mismatch';
            end if;
        end if;
    end loop;
    return new;
end $$;
revoke all on function counseling_integrity.check_parent_scope() from public, anon, authenticated, service_role;

do $$
declare target_table text;
begin
    foreach target_table in array array[
        'sessions', 'generated_notes', 'evidence_items', 'verification_reports', 'case_memory_chunks'
    ] loop
        execute format('create trigger counseling_parent_scope before insert or update on public.%I
                        for each row execute function counseling_integrity.check_parent_scope()', target_table);
    end loop;
end $$;
