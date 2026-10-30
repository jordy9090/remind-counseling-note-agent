-- Review candidates are immutable; editing creates a new snapshot. The backend
-- forwards the verified user's JWT, matching existing counseling persistence.
create table public.voucher_documents (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references public.cases(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  operation_key uuid not null,
  request_hash text not null,
  template text not null check (template in ('form10', 'form26')),
  snapshot jsonb not null,
  fingerprint text not null,
  privacy_status text not null check (privacy_status in ('applied', 'degraded')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid,
  unique (user_id, operation_key),
  check ((reviewed_at is null and reviewed_by is null) or (reviewed_at is not null and reviewed_by = user_id))
);
create index voucher_documents_owner_case on public.voucher_documents(user_id, case_id, created_at desc);
alter table public.voucher_documents enable row level security;
create policy voucher_documents_owner on public.voucher_documents for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));
revoke all on public.voucher_documents from anon, authenticated;
grant select, insert, update, delete on public.voucher_documents to authenticated;
grant all on public.voucher_documents to service_role;

create function public.guard_voucher_snapshot() returns trigger language plpgsql set search_path = '' as $$
declare source_id text;
begin
  if tg_op = 'INSERT' then
    if new.reviewed_at is not null or new.reviewed_by is not null then
      raise exception 'voucher requires a separate review acknowledgement';
    end if;
    if jsonb_typeof(new.snapshot->'sources') is distinct from 'object' then
      raise exception 'voucher sources must be an object';
    end if;
    if not exists (select 1 from public.cases c where c.id = new.case_id and c.user_id = new.user_id::text) then
      raise exception 'voucher owner mismatch';
    end if;
    -- Serialize snapshot insertion against deletion of a referenced note.
    for source_id in select jsonb_object_keys(new.snapshot->'sources') loop
      perform 1 from public.generated_notes n where n.id = source_id::uuid
        and n.case_id = new.case_id and n.user_id = new.user_id::text for key share;
      if not found then raise exception 'voucher source missing'; end if;
    end loop;
  elsif (to_jsonb(new) - 'reviewed_at' - 'reviewed_by') is distinct from
        (to_jsonb(old) - 'reviewed_at' - 'reviewed_by') or old.reviewed_at is not null then
    raise exception 'voucher snapshot is immutable';
  elsif new.reviewed_at is null or new.reviewed_by is distinct from new.user_id then
    raise exception 'voucher review acknowledgement required';
  else
    new.reviewed_at := now();
  end if;
  return new;
end $$;
create trigger voucher_snapshot_guard before insert or update on public.voucher_documents
  for each row execute function public.guard_voucher_snapshot();

revoke all on function public.guard_voucher_snapshot() from public;

-- Deleting a source note must also remove snapshots containing its copied text.
create function public.delete_note_voucher_documents() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  delete from public.voucher_documents where snapshot->'sources' ? old.id::text;
  return old;
end $$;
create trigger delete_note_voucher_documents after delete on public.generated_notes
  for each row execute function public.delete_note_voucher_documents();
revoke all on function public.delete_note_voucher_documents() from public;
