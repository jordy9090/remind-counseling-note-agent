-- Additive production raw-evidence foundation. Stores deidentified transcript turns only.
create table if not exists public.transcript_turns (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  counselor_id text not null,
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid not null references public.sessions(id) on delete cascade,
  turn_index integer not null check (turn_index >= 0),
  speaker_role text not null check (speaker_role in ('counselor', 'client', 'unknown')),
  start_ms integer,
  end_ms integer,
  sanitized_text text not null,
  source_type text not null default 'transcript',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_transcript_turns_session_index unique(session_id, turn_index),
  constraint ck_transcript_turns_time_order check (start_ms is null or end_ms is null or end_ms >= start_ms)
);

create index if not exists idx_transcript_turns_owner_span
  on public.transcript_turns(user_id, case_id, session_id, turn_index);
create index if not exists idx_transcript_turns_session_index
  on public.transcript_turns(session_id, turn_index);
alter table public.transcript_turns enable row level security;

drop policy if exists user_owns_rows on public.transcript_turns;
create policy user_owns_rows on public.transcript_turns
  for all to authenticated
  using (
    (select auth.uid())::text = user_id
    and counselor_id = user_id
    and exists (
      select 1 from public.cases c
      where c.id = transcript_turns.case_id and c.user_id = transcript_turns.user_id
    )
    and exists (
      select 1 from public.sessions s
      where s.id = transcript_turns.session_id
        and s.case_id = transcript_turns.case_id
        and s.user_id = transcript_turns.user_id
    )
  )
  with check (
    (select auth.uid())::text = user_id
    and counselor_id = user_id
    and exists (
      select 1 from public.cases c
      where c.id = transcript_turns.case_id and c.user_id = transcript_turns.user_id
    )
    and exists (
      select 1 from public.sessions s
      where s.id = transcript_turns.session_id
        and s.case_id = transcript_turns.case_id
        and s.user_id = transcript_turns.user_id
    )
  );

revoke all on table public.transcript_turns from anon;
grant select, insert, update, delete on table public.transcript_turns to authenticated;
