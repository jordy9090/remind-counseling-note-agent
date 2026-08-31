-- Deterministic raw transcript windows for dense candidate retrieval.
create table if not exists public.transcript_windows (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  counselor_id text not null,
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid not null references public.sessions(id) on delete cascade,
  start_turn_index integer not null check (start_turn_index >= 0),
  end_turn_index integer not null,
  window_text text not null,
  source_ref text not null,
  embedding extensions.vector(1536),
  embedding_model text,
  content_hash text not null,
  embedding_updated_at timestamptz,
  created_at timestamptz not null default now(),
  constraint ck_transcript_windows_span_order check (start_turn_index <= end_turn_index),
  constraint uq_transcript_windows_session_span unique(session_id, start_turn_index, end_turn_index),
  constraint uq_transcript_windows_source_ref unique(source_ref)
);

create index if not exists idx_transcript_windows_owner_case
  on public.transcript_windows(user_id, case_id, session_id);
create index if not exists idx_transcript_windows_content_hash
  on public.transcript_windows(content_hash);

alter table public.transcript_windows enable row level security;

drop policy if exists user_owns_rows on public.transcript_windows;
create policy user_owns_rows on public.transcript_windows
  for all to authenticated
  using ((select auth.uid())::text = user_id)
  with check ((select auth.uid())::text = user_id);

revoke all on table public.transcript_windows from anon;
grant select, insert, update, delete on table public.transcript_windows to authenticated;

create or replace function public.match_transcript_windows(
  query_embedding extensions.vector(1536),
  filter_user_id text,
  filter_case_id text,
  match_count integer default 12
)
returns table (
  window_id uuid,
  session_id uuid,
  session_number integer,
  start_turn_index integer,
  end_turn_index integer,
  source_ref text,
  window_text text,
  similarity_score double precision,
  retrieval_method text
)
language sql
stable
security invoker
as $$
  select
    w.id as window_id,
    w.session_id,
    s.session_number,
    w.start_turn_index,
    w.end_turn_index,
    w.source_ref,
    w.window_text,
    (1 - (w.embedding operator(extensions.<=>) query_embedding))::double precision as similarity_score,
    'transcript_window_dense'::text as retrieval_method
  from public.transcript_windows w
  join public.sessions s on s.id = w.session_id
  where filter_user_id is not null
    and filter_case_id is not null
    and w.user_id = filter_user_id
    and w.case_id = filter_case_id
    and s.user_id = filter_user_id
    and s.case_id = filter_case_id
    and w.embedding is not null
  order by w.embedding operator(extensions.<=>) query_embedding asc
  limit least(greatest(match_count, 1), 50);
$$;

revoke all on function public.match_transcript_windows(extensions.vector, text, text, integer) from public, anon;
grant execute on function public.match_transcript_windows(extensions.vector, text, text, integer)
  to authenticated, service_role;
