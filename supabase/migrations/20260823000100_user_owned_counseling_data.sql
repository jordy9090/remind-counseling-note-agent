-- User ownership and RLS for counseling data.
-- Existing rows without a trustworthy owner remain inaccessible to authenticated users.

alter table public.cases add column if not exists user_id text;
alter table public.sessions add column if not exists user_id text;
alter table public.generated_notes add column if not exists user_id text;
alter table public.evidence_items add column if not exists user_id text;
alter table public.verification_reports add column if not exists user_id text;
alter table public.counseling_drafts add column if not exists user_id text;
alter table public.case_memory_chunks add column if not exists user_id text;
alter table public.retrieval_logs add column if not exists user_id text;

update public.cases
set user_id = counselor_id
where user_id is null and counselor_id is not null and counselor_id <> '';

update public.sessions as child
set user_id = owner.user_id
from public.cases as owner
where child.case_id = owner.id and child.user_id is null and owner.user_id is not null;

update public.generated_notes as child
set user_id = owner.user_id
from public.cases as owner
where child.case_id = owner.id and child.user_id is null and owner.user_id is not null;

update public.evidence_items as child
set user_id = owner.user_id
from public.cases as owner
where child.case_id = owner.id and child.user_id is null and owner.user_id is not null;

update public.verification_reports as child
set user_id = owner.user_id
from public.cases as owner
where child.case_id = owner.id and child.user_id is null and owner.user_id is not null;

update public.case_memory_chunks
set user_id = counselor_id
where user_id is null and counselor_id is not null and counselor_id <> '';

update public.retrieval_logs
set user_id = counselor_id
where user_id is null and counselor_id is not null and counselor_id <> '';

create index if not exists idx_cases_user_id on public.cases(user_id);
create index if not exists idx_sessions_user_id on public.sessions(user_id);
create index if not exists idx_generated_notes_user_id on public.generated_notes(user_id);
create index if not exists idx_evidence_items_user_id on public.evidence_items(user_id);
create index if not exists idx_verification_reports_user_id on public.verification_reports(user_id);
create index if not exists idx_counseling_drafts_user_id on public.counseling_drafts(user_id);
create index if not exists idx_case_memory_chunks_user_id on public.case_memory_chunks(user_id);
create index if not exists idx_retrieval_logs_user_id on public.retrieval_logs(user_id);

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'cases',
    'sessions',
    'generated_notes',
    'evidence_items',
    'verification_reports',
    'counseling_drafts',
    'case_memory_chunks',
    'retrieval_logs'
  ]
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists user_owns_rows on public.%I', table_name);
    execute format(
      'create policy user_owns_rows on public.%I for all to authenticated using ((select auth.uid())::text = user_id) with check ((select auth.uid())::text = user_id)',
      table_name
    );
    execute format('grant select, insert, update, delete on table public.%I to authenticated', table_name);
    execute format('revoke all on table public.%I from anon', table_name);
  end loop;
end $$;

drop policy if exists authenticated_read_kb_documents on public.kb_documents;
create policy authenticated_read_kb_documents
  on public.kb_documents for select to authenticated using (true);

drop policy if exists authenticated_read_kb_chunks on public.kb_chunks;
create policy authenticated_read_kb_chunks
  on public.kb_chunks for select to authenticated using (true);

grant select on table public.kb_documents to authenticated;
grant select on table public.kb_chunks to authenticated;
revoke all on table public.kb_documents from anon;
revoke all on table public.kb_chunks from anon;
