create or replace function public.match_evidence_episodes(
  query_embedding extensions.vector(1536),
  filter_user_id text,
  filter_case_id text,
  filter_episode_types text[] default null,
  match_count integer default 12
)
returns table (
  episode_id uuid,
  session_id uuid,
  session_number integer,
  episode_type text,
  start_turn_index integer,
  end_turn_index integer,
  source_ref text,
  episode_text text,
  similarity_score double precision,
  retrieval_method text,
  metadata jsonb
)
language sql
stable
as $$
  select
    e.id as episode_id,
    e.session_id,
    s.session_number,
    e.episode_type,
    e.start_turn_index,
    e.end_turn_index,
    e.source_ref,
    e.episode_text,
    (1 - (e.embedding operator(extensions.<=>) query_embedding))::double precision as similarity_score,
    'evidence_episode_dense'::text as retrieval_method,
    e.metadata_json as metadata
  from public.evidence_episodes e
  join public.sessions s on s.id = e.session_id
  where filter_user_id is not null
    and filter_case_id is not null
    and e.user_id = filter_user_id
    and e.case_id = filter_case_id
    and s.user_id = filter_user_id
    and s.case_id = filter_case_id
    and e.embedding is not null
    and (filter_episode_types is null or e.episode_type = any(filter_episode_types))
  order by e.embedding operator(extensions.<=>) query_embedding asc
  limit least(greatest(match_count, 1), 50);
$$;

revoke all on function public.match_evidence_episodes(extensions.vector, text, text, text[], integer) from public, anon;
grant execute on function public.match_evidence_episodes(extensions.vector, text, text, text[], integer) to authenticated, service_role;
