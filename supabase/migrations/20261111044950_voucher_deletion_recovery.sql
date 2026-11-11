-- Recovery keeps the immutable output snapshot. Detached links remain historical
-- metadata and never count as live note references after restoration.
alter table public.voucher_documents
  add column detached_source_ids uuid[] not null default '{}',
  add column restored_from uuid;
create policy voucher_no_detached_insert on public.voucher_documents
  as restrictive for insert to authenticated with check (cardinality(detached_source_ids) = 0 and restored_from is null);

create schema voucher_recovery;
revoke all on schema voucher_recovery from public, anon, authenticated, service_role;
grant usage on schema voucher_recovery to authenticated;

create table voucher_recovery.deletions (
  event_id uuid primary key default gen_random_uuid(),
  document_id uuid not null,
  owner_id uuid not null references auth.users(id) on delete cascade,
  case_id text not null references public.cases(id) on delete cascade,
  template text not null,
  deleted_at timestamptz not null,
  expires_at timestamptz not null,
  deleted_by uuid,
  actor_role text not null,
  source_note_id uuid,
  backup jsonb,
  unavailable_sources uuid[] not null,
  restored_at timestamptz,
  restored_by uuid
);
create index voucher_deletions_owner_case on voucher_recovery.deletions(owner_id, case_id, deleted_at desc);
create index voucher_deletions_expiry on voucher_recovery.deletions(expires_at) where backup is not null;
create index voucher_deletions_age on voucher_recovery.deletions(deleted_at);
create index voucher_deletions_case on voucher_recovery.deletions(case_id);
alter table voucher_recovery.deletions enable row level security;

-- Only the genuine note trigger can establish the cause of a cascaded delete.
-- Both the marker and the backup are written in the deleting transaction.
create table voucher_recovery.source_context (
  transaction_id xid8 not null,
  source_id uuid not null,
  owner_id text not null,
  primary key (transaction_id, source_id)
);
alter table voucher_recovery.source_context enable row level security;
revoke all on all tables in schema voucher_recovery from public, anon, authenticated, service_role;

create function voucher_recovery.capture_deletion() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  source_id uuid;
  event_time timestamptz := clock_timestamp();
begin
  if tg_relid <> 'public.voucher_documents'::regclass or tg_op <> 'DELETE'
     or tg_when <> 'BEFORE' or tg_level <> 'ROW' then
    raise insufficient_privilege using message = 'Invalid voucher archive trigger context';
  end if;
  -- Erasing the case or account also erases its recovery history.
  perform 1 from auth.users u join public.cases c on c.user_id = u.id::text
    where u.id = old.user_id and c.id = old.case_id for key share of u, c;
  if not found then return old; end if;
  select s.source_id into source_id from voucher_recovery.source_context s
    where s.transaction_id = pg_current_xact_id() and s.owner_id = old.user_id::text
      and exists (select from jsonb_object_keys(old.snapshot->'sources') k where k::uuid = s.source_id);
  insert into voucher_recovery.deletions
    (document_id, owner_id, case_id, template, deleted_at, expires_at, deleted_by,
     actor_role, source_note_id, backup, unavailable_sources)
    values (old.id, old.user_id, old.case_id, old.template, event_time, event_time + interval '7 days',
      auth.uid(), coalesce(nullif(current_setting('role', true), 'none'), session_user),
      source_id, to_jsonb(old), old.detached_source_ids);
  return old;
end $$;
revoke all on function voucher_recovery.capture_deletion() from public, anon, authenticated, service_role;
create trigger archive_voucher_before_delete before delete on public.voucher_documents
  for each row execute function voucher_recovery.capture_deletion();

create or replace function public.delete_note_voucher_documents() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_relid <> 'public.generated_notes'::regclass or tg_op <> 'DELETE'
     or tg_when <> 'AFTER' or tg_level <> 'ROW' then
    raise insufficient_privilege using message = 'Invalid voucher cleanup trigger context';
  end if;
  if old.user_id is null then return old; end if;
  insert into voucher_recovery.source_context values (pg_current_xact_id(), old.id, old.user_id);
  delete from public.voucher_documents as v
    where v.user_id::text = old.user_id and not (old.id = any(v.detached_source_ids))
      and exists (select from jsonb_object_keys(v.snapshot->'sources') k where k::uuid = old.id);
  delete from voucher_recovery.source_context
    where transaction_id = pg_current_xact_id() and source_id = old.id;
  -- Also remember originals removed while a voucher was already in the bin.
  -- Reusing a deleted note's UUID must never attach a recovery to its replacement.
  update voucher_recovery.deletions e set unavailable_sources = array_append(e.unavailable_sources, old.id)
    where e.owner_id::text = old.user_id and e.backup is not null and e.expires_at > clock_timestamp()
      and not (old.id = any(e.unavailable_sources))
      and exists (select from jsonb_object_keys(e.backup->'snapshot'->'sources') k where k::uuid = old.id);
  return old;
end $$;
revoke all on function public.delete_note_voucher_documents() from public, anon, authenticated, service_role;

-- Extend the original insert guard only for trusted recoveries. The restrictive
-- insert policy disallows supplying detached IDs through authenticated clients.
create or replace function public.guard_voucher_snapshot() returns trigger language plpgsql set search_path = '' as $$
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
    for source_id in select jsonb_object_keys(new.snapshot->'sources') loop
      if not (source_id::uuid = any(new.detached_source_ids)) then
        perform 1 from public.generated_notes n where n.id = source_id::uuid
          and n.case_id = new.case_id and n.user_id = new.user_id::text for key share;
        if not found then raise exception 'voucher source missing'; end if;
      end if;
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
revoke all on function public.guard_voucher_snapshot() from public, anon, authenticated, service_role;

create function voucher_recovery.history(p_case text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'event_id', e.event_id, 'document_id', e.document_id, 'template', e.template,
    'deleted_at', e.deleted_at, 'expires_at', e.expires_at, 'deleted_by', e.deleted_by,
    'actor_role', e.actor_role, 'by_me', e.deleted_by = (select auth.uid()),
    'reason', case when e.source_note_id is null then 'direct' else 'source' end,
    'restored_at', e.restored_at, 'can_restore', e.backup is not null and e.expires_at > now()
  ) order by e.deleted_at desc, e.event_id), '[]'::jsonb)
  from voucher_recovery.deletions e join public.cases c on c.id = e.case_id
  where e.owner_id = (select auth.uid()) and c.user_id = e.owner_id::text and c.id = p_case
    and e.deleted_at > now() - interval '90 days';
$$;

create function voucher_recovery.restore(p_event uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  entry voucher_recovery.deletions%rowtype;
  doc public.voucher_documents%rowtype;
  source_id uuid;
begin
  select e.* into entry from voucher_recovery.deletions e join public.cases c on c.id = e.case_id
    where e.event_id = p_event and e.owner_id = (select auth.uid()) and c.user_id = e.owner_id::text
    for update of e for share of c;
  if not found then return jsonb_build_object('status','missing'); end if;
  if entry.restored_at is not null then
    if exists (select from public.voucher_documents v where v.id = entry.document_id and v.user_id = entry.owner_id
          and v.case_id = entry.case_id and v.restored_from = entry.event_id) then
      return jsonb_build_object('status','ok','id',entry.document_id);
    end if;
    return jsonb_build_object('status','consumed');
  end if;
  if entry.expires_at <= clock_timestamp() or entry.backup is null then
    return jsonb_build_object('status','expired');
  end if;
  doc := jsonb_populate_record(null::public.voucher_documents, entry.backup);
  doc.reviewed_at := null;
  doc.reviewed_by := null;
  doc.detached_source_ids := entry.unavailable_sources;
  for source_id in select distinct k::uuid from jsonb_object_keys(doc.snapshot->'sources') k order by 1 loop
    if not (source_id = any(doc.detached_source_ids)) then
      perform 1 from public.generated_notes n where n.id = source_id and n.case_id = entry.case_id
        and n.user_id = entry.owner_id::text for key share;
      if not found then doc.detached_source_ids := array_append(doc.detached_source_ids, source_id); end if;
    end if;
  end loop;
  -- Preserve the original prepare idempotency key and distinguish retries of
  -- this restore from an unrelated document that happens to reuse its ID.
  doc.restored_from := entry.event_id;
  insert into public.voucher_documents select doc.* on conflict do nothing;
  if not found then return jsonb_build_object('status','conflict'); end if;
  update voucher_recovery.deletions set backup = null, unavailable_sources = '{}',
    restored_at = clock_timestamp(), restored_by = auth.uid() where event_id = p_event;
  return jsonb_build_object('status','ok','id',doc.id);
end $$;

create function public.voucher_deletion_history(p_case text) returns jsonb
language sql stable security invoker set search_path = '' as $$ select voucher_recovery.history(p_case) $$;
create function public.restore_deleted_voucher(p_event uuid) returns jsonb
language sql volatile security invoker set search_path = '' as $$ select voucher_recovery.restore(p_event) $$;
revoke all on function voucher_recovery.history(text), voucher_recovery.restore(uuid),
  public.voucher_deletion_history(text), public.restore_deleted_voucher(uuid) from public, anon, authenticated, service_role;
grant execute on function voucher_recovery.history(text), voucher_recovery.restore(uuid),
  public.voucher_deletion_history(text), public.restore_deleted_voucher(uuid) to authenticated;

create function voucher_recovery.purge_expired() returns void
language plpgsql security invoker set search_path = '' as $$
begin
  update voucher_recovery.deletions set backup = null, unavailable_sources = '{}'
    where backup is not null and expires_at <= clock_timestamp();
  delete from voucher_recovery.deletions where deleted_at <= clock_timestamp() - interval '90 days';
end $$;
revoke all on function voucher_recovery.purge_expired() from public, anon, authenticated, service_role;

-- Hosted scheduler (the standalone Windows PostgreSQL test exercises the body directly).
create extension if not exists pg_cron with schema pg_catalog;
select cron.schedule('voucher-deletion-retention', '*/10 * * * *', 'select voucher_recovery.purge_expired()');
