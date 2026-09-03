-- Research-only schema retained for the archived episode extraction comparisons.
-- This file is not part of the production Supabase migration chain.
create table if not exists public.evidence_episodes (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  counselor_id text not null,
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid not null references public.sessions(id) on delete cascade,
  episode_type text not null check (episode_type in ('intervention_response', 'client_event_state')),
  start_turn_index integer not null check (start_turn_index >= 0),
  end_turn_index integer not null,
  source_ref text not null,
  episode_text text not null,
  metadata_json jsonb not null default '{}'::jsonb,
  embedding extensions.vector(1536),
  embedding_model text,
  content_hash text,
  embedding_updated_at timestamptz,
  created_at timestamptz not null default now(),
  constraint ck_evidence_episodes_span_order check (start_turn_index <= end_turn_index),
  constraint uq_evidence_episodes_span_type unique(session_id, start_turn_index, end_turn_index, episode_type),
  constraint uq_evidence_episodes_source_ref_type unique(source_ref, episode_type)
);

create index if not exists idx_evidence_episodes_owner_session
  on public.evidence_episodes(user_id, case_id, session_id);
create index if not exists idx_evidence_episodes_owner_type
  on public.evidence_episodes(user_id, case_id, episode_type);
create index if not exists idx_evidence_episodes_content_hash
  on public.evidence_episodes(content_hash);

alter table public.evidence_episodes enable row level security;

drop policy if exists user_owns_rows on public.evidence_episodes;
create policy user_owns_rows on public.evidence_episodes
  for all to authenticated
  using ((select auth.uid())::text = user_id)
  with check ((select auth.uid())::text = user_id);

revoke all on table public.evidence_episodes from anon;
grant select, insert, update, delete on table public.evidence_episodes to authenticated;
