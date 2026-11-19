-- Preserve the private enrollment boundary while allowing deletion to finish.
create or replace function beta_retention.check_write() returns trigger
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
        -- FK SET NULL removes only a reference to an already deleted source.
        -- Direct detachment, content edits and new links still use the guard.
        if tg_op = 'UPDATE' and tg_relid = 'public.generated_notes'::regclass
           and pg_trigger_depth() > 1
           and to_jsonb(new)->>'source_note_id' is null
           and to_jsonb(old)->>'source_note_id' is not null
           and to_jsonb(new) - 'source_note_id' = to_jsonb(old) - 'source_note_id'
           and not exists (select from public.generated_notes
                           where id = (to_jsonb(old)->>'source_note_id')::uuid) then
            return new;
        end if;
        if tg_op = 'UPDATE' and old_key is not distinct from case_key
           and new.user_id is not distinct from old.user_id then
            -- This row is already locked. Erasure must delete it, including the
            -- three tables explicitly deleted by erase_due without case FKs.
            -- Reacquiring enrollment locks here would invert that lock order.
            select * into scope from beta_retention.enrollments where case_id = case_key;
        else
            -- Inserts and ownership/scope changes must serialize with erasure.
            select * into scope from beta_retention.enrollments where case_id = case_key for share;
        end if;
        if not found or scope.owner_id::text is distinct from new.user_id::text
           or scope.withdrawn_at is not null or scope.erased_at is not null or scope.ends_at <= clock_timestamp() then
            raise exception 'Beta case is unavailable';
        end if;
    end if;
    return new;
end $$;
revoke all on function beta_retention.check_write() from public, anon, authenticated, service_role;
