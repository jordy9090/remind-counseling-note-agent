-- The installed source-note trigger keeps running when API roles lose EXECUTE.
-- Check the event as well because revoking EXECUTE does not disable old bindings.
create or replace function public.delete_note_voucher_documents() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_relid <> 'public.generated_notes'::pg_catalog.regclass or
     tg_op <> 'DELETE' or tg_when <> 'AFTER' or tg_level <> 'ROW' then
    raise exception using errcode = '42501', message = 'Invalid voucher cleanup trigger context';
  end if;
  -- The insert guard validates each source as a UUID and matches its owner.
  -- Compare the same way here, including previously accepted UUID spellings.
  delete from public.voucher_documents as v
    where v.user_id::pg_catalog.text = old.user_id
      and exists (
        select 1 from pg_catalog.jsonb_object_keys(v.snapshot->'sources') as source(key)
        where source.key::pg_catalog.uuid = old.id
      );
  return old;
end $$;

revoke execute on function public.delete_note_voucher_documents() from public, anon, authenticated;

-- Snapshot source IDs cannot follow a primary-key update inside immutable JSON.
create function public.reject_generated_note_id_change() returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  raise exception using errcode = '23514', message = 'A generated note ID cannot be changed';
end $$;
create trigger generated_note_id_immutable before update of id on public.generated_notes
  for each row when (old.id is distinct from new.id)
  execute function public.reject_generated_note_id_change();
revoke execute on function public.reject_generated_note_id_change() from public, anon, authenticated;
