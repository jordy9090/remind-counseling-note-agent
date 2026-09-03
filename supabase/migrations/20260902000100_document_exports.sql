-- Document export history: records completed/failed export attempts so the
-- case dashboard can show 문서 변환 상태. Non-destructive, additive only.
-- Note: exports run synchronously, so only terminal states are stored;
-- 'processing' is reserved for a future async pipeline.

create table if not exists public.document_exports (
  id uuid primary key default gen_random_uuid(),
  case_id text not null,
  session_number integer,
  document_type text not null default '',
  format text not null default '',
  title text not null default '',
  status text not null default 'completed',
  error text,
  user_id text,
  created_at timestamptz not null default now()
);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'document_exports_status_valid'
  ) then
    alter table public.document_exports
      add constraint document_exports_status_valid
      check (status in ('processing', 'completed', 'failed'));
  end if;
end $$;

create index if not exists idx_document_exports_case_recent
  on public.document_exports(case_id, created_at desc);

create index if not exists idx_document_exports_user_id
  on public.document_exports(user_id);

alter table public.document_exports enable row level security;
drop policy if exists user_owns_rows on public.document_exports;
create policy user_owns_rows on public.document_exports
  for all to authenticated
  using ((select auth.uid())::text = user_id)
  with check ((select auth.uid())::text = user_id);
grant select, insert, update, delete on table public.document_exports to authenticated;
revoke all on table public.document_exports from anon;
