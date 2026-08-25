-- Keep dense case-memory retrieval tenant-scoped even when a backend
-- service-role credential bypasses row-level security.

create or replace function public.match_case_memory_chunks(
  query_embedding extensions.vector(1536),
  filter_counselor_id text,
  filter_case_id text,
  filter_field_types text[] default null,
  match_count integer default 5
)
returns table (
  chunk_id uuid,
  session_id uuid,
  source_note_id uuid,
  source_ref text,
  case_id text,
  counselor_id text,
  session_number integer,
  session_date date,
  field_type text,
  chunk_text text,
  similarity_score double precision,
  retrieval_method text,
  metadata jsonb
)
language sql
stable
as $$
  select
    c.id as chunk_id,
    c.session_id,
    c.source_note_id,
    c.source_ref,
    c.case_id,
    c.counselor_id,
    c.session_number,
    c.session_date,
    c.field_type,
    c.chunk_text,
    (1 - (c.embedding operator(extensions.<=>) query_embedding))::double precision as similarity_score,
    'case_memory_dense'::text as retrieval_method,
    c.metadata_json as metadata
  from public.case_memory_chunks c
  where filter_counselor_id is not null
    and filter_case_id is not null
    and c.user_id = filter_counselor_id
    and c.counselor_id = filter_counselor_id
    and c.case_id = filter_case_id
    and c.embedding is not null
    and (filter_field_types is null or c.field_type = any(filter_field_types))
  order by
    (c.embedding operator(extensions.<=>) query_embedding) asc,
    c.session_number desc nulls last,
    c.created_at desc
  limit least(greatest(match_count, 1), 5);
$$;
