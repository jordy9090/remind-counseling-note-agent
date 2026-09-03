-- Case scheduling metadata and session transcript status.
-- Non-destructive: adds nullable/defaulted columns and named check constraints only.
-- Safe on tables with existing data (no rewrites, no drops, no data loss).

-- B. cases: 전체 예정 회기 수 / 다음 상담 예정일
alter table public.cases
  add column if not exists total_scheduled_session_count integer;

alter table public.cases
  add column if not exists next_scheduled_date date;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'cases_total_scheduled_session_count_nonnegative'
  ) then
    alter table public.cases
      add constraint cases_total_scheduled_session_count_nonnegative
      check (total_scheduled_session_count is null or total_scheduled_session_count >= 0);
  end if;
end $$;

-- C. sessions: 축어록 진행 상태
-- 현재 파이프라인은 동기 처리(업로드→전사→반영 후 회기 저장)라서 저장 시점에는
-- none 또는 completed만 기록된다. pending/processing/failed는 향후 비동기 전사
-- 도입 시 사용할 수 있도록 허용값에 포함해 둔다.
alter table public.sessions
  add column if not exists transcript_status text not null default 'none';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'sessions_transcript_status_valid'
  ) then
    alter table public.sessions
      add constraint sessions_transcript_status_valid
      check (transcript_status in ('none', 'pending', 'processing', 'completed', 'failed'));
  end if;
end $$;

create index if not exists idx_generated_notes_case_recent
  on public.generated_notes(case_id, created_at desc);
