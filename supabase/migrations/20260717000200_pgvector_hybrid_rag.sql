-- Re:mind pgvector/hybrid retrieval schema.
-- Non-destructive: adds nullable columns, indexes, and RPC functions.
-- Chosen embedding model default: text-embedding-3-small, 1536 dimensions.

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

alter table public.kb_documents
  add column if not exists source_org text not null default '',
  add column if not exists checksum text,
  add column if not exists metadata_json jsonb not null default '{}'::jsonb,
  add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'kb_documents_doc_category_check'
      and conrelid = 'public.kb_documents'::regclass
  ) then
    alter table public.kb_documents drop constraint kb_documents_doc_category_check;
  end if;
end $$;

alter table public.kb_documents
  add constraint kb_documents_doc_category_check
  check (
    doc_category in (
      'document_template',
      'ethics_rule',
      'privacy_rule',
      'security_rule',
      'writing_example',
      'internal_policy',
      'session_note_template',
      'supervision_report_template',
      'termination_report_template',
      'counseling_ethics',
      'privacy_law',
      'deidentification_guideline',
      'internal_security_policy'
    )
  );

alter table public.kb_chunks
  add column if not exists section_path text not null default '',
  add column if not exists document_type text not null default '',
  add column if not exists allowed_use text not null default '',
  add column if not exists counselor_review_required boolean not null default false,
  add column if not exists source_ref text,
  add column if not exists embedding extensions.vector(1536),
  add column if not exists embedding_model text,
  add column if not exists content_hash text,
  add column if not exists embedding_updated_at timestamptz;

alter table public.kb_chunks
  add column if not exists search_text tsvector
  generated always as (
    to_tsvector(
      'simple',
      coalesce(chunk_text, '') || ' ' ||
      coalesce(section_path, '') || ' ' ||
      coalesce(document_type, '') || ' ' ||
      coalesce(chunk_type, '')
    )
  ) stored;

create table if not exists public.case_memory_chunks (
  id uuid primary key default gen_random_uuid(),
  counselor_id text not null,
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete cascade,
  session_number integer,
  session_date date,
  field_type text not null,
  chunk_text text not null,
  source_ref text not null,
  metadata_json jsonb not null default '{}'::jsonb,
  embedding extensions.vector(1536),
  embedding_model text,
  content_hash text,
  created_at timestamptz not null default now()
);

create index if not exists idx_kb_documents_hybrid_filters
  on public.kb_documents(doc_category, source_type, authority_level, allowed_use);

create index if not exists idx_kb_chunks_hybrid_filters
  on public.kb_chunks(document_id, document_type, allowed_use, chunk_type);

create index if not exists idx_kb_chunks_search_text
  on public.kb_chunks using gin(search_text);

create index if not exists idx_kb_chunks_content_hash
  on public.kb_chunks(content_hash);

create index if not exists idx_case_memory_scope
  on public.case_memory_chunks(counselor_id, case_id, session_number desc, created_at desc);

create index if not exists idx_case_memory_field
  on public.case_memory_chunks(counselor_id, case_id, field_type);

create index if not exists idx_case_memory_content_hash
  on public.case_memory_chunks(content_hash);

-- Add HNSW indexes later when the corpus is large enough to justify ANN tuning:
-- create index idx_kb_chunks_embedding_hnsw on public.kb_chunks
--   using hnsw (embedding extensions.vector_cosine_ops);
-- create index idx_case_memory_embedding_hnsw on public.case_memory_chunks
--   using hnsw (embedding extensions.vector_cosine_ops);

create or replace function public.match_kb_chunks(
  query_embedding extensions.vector(1536),
  match_count integer default 10,
  filter_doc_categories text[] default null,
  filter_document_type text default null,
  filter_allowed_uses text[] default null,
  filter_authority_levels text[] default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  source_ref text,
  source_url text,
  title text,
  doc_category text,
  document_type text,
  allowed_use text,
  authority_level text,
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
    d.id as document_id,
    coalesce(c.source_ref, 'kb:' || c.id::text) as source_ref,
    d.source_url,
    d.title,
    d.doc_category,
    coalesce(nullif(c.document_type, ''), d.source_type) as document_type,
    coalesce(nullif(c.allowed_use, ''), d.allowed_use) as allowed_use,
    d.authority_level,
    c.chunk_text,
    (1 - (c.embedding <=> query_embedding))::double precision as similarity_score,
    'dense'::text as retrieval_method,
    (
      c.metadata_json ||
      jsonb_build_object(
        'section_path', c.section_path,
        'source_org', d.source_org,
        'counselor_review_required', c.counselor_review_required
      )
    ) as metadata
  from public.kb_chunks c
  join public.kb_documents d on d.id = c.document_id
  where c.embedding is not null
    and (filter_doc_categories is null or d.doc_category = any(filter_doc_categories))
    and (filter_document_type is null or coalesce(nullif(c.document_type, ''), d.source_type) in (filter_document_type, ''))
    and (filter_allowed_uses is null or coalesce(nullif(c.allowed_use, ''), d.allowed_use) = any(filter_allowed_uses))
    and (filter_authority_levels is null or d.authority_level = any(filter_authority_levels))
  order by c.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;

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
    c.source_ref,
    c.case_id,
    c.counselor_id,
    c.session_number,
    c.session_date,
    c.field_type,
    c.chunk_text,
    (1 - (c.embedding <=> query_embedding))::double precision as similarity_score,
    'case_memory_dense'::text as retrieval_method,
    c.metadata_json as metadata
  from public.case_memory_chunks c
  where filter_counselor_id is not null
    and filter_case_id is not null
    and c.counselor_id = filter_counselor_id
    and c.case_id = filter_case_id
    and c.embedding is not null
    and (filter_field_types is null or c.field_type = any(filter_field_types))
  order by
    (c.embedding <=> query_embedding) asc,
    c.session_number desc nulls last,
    c.created_at desc
  limit least(greatest(match_count, 1), 5);
$$;

create or replace function public.hybrid_search_kb(
  query_text text,
  query_embedding extensions.vector(1536) default null,
  match_count integer default 10,
  filter_doc_categories text[] default null,
  filter_document_type text default null,
  filter_allowed_uses text[] default null,
  filter_authority_levels text[] default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  source_ref text,
  source_url text,
  title text,
  doc_category text,
  document_type text,
  allowed_use text,
  authority_level text,
  chunk_text text,
  similarity_score double precision,
  retrieval_method text,
  metadata jsonb
)
language sql
stable
as $$
  with filtered as (
    select
      c.id as chunk_id,
      d.id as document_id,
      coalesce(c.source_ref, 'kb:' || c.id::text) as source_ref,
      d.source_url,
      d.title,
      d.doc_category,
      coalesce(nullif(c.document_type, ''), d.source_type) as document_type,
      coalesce(nullif(c.allowed_use, ''), d.allowed_use) as allowed_use,
      d.authority_level,
      c.chunk_text,
      c.search_text,
      c.embedding,
      (
        c.metadata_json ||
        jsonb_build_object(
          'section_path', c.section_path,
          'source_org', d.source_org,
          'counselor_review_required', c.counselor_review_required
        )
      ) as metadata
    from public.kb_chunks c
    join public.kb_documents d on d.id = c.document_id
    where (filter_doc_categories is null or d.doc_category = any(filter_doc_categories))
      and (filter_document_type is null or coalesce(nullif(c.document_type, ''), d.source_type) in (filter_document_type, ''))
      and (filter_allowed_uses is null or coalesce(nullif(c.allowed_use, ''), d.allowed_use) = any(filter_allowed_uses))
      and (filter_authority_levels is null or d.authority_level = any(filter_authority_levels))
  ),
  tsq as (
    select websearch_to_tsquery('simple', coalesce(query_text, '')) as value
  ),
  dense_ranked as (
    select
      f.chunk_id,
      row_number() over (order by f.embedding <=> query_embedding) as rank_position
    from filtered f
    where query_embedding is not null
      and f.embedding is not null
    limit 50
  ),
  keyword_ranked as (
    select
      f.chunk_id,
      row_number() over (order by ts_rank_cd(f.search_text, tsq.value) desc) as rank_position
    from filtered f, tsq
    where coalesce(query_text, '') <> ''
      and f.search_text @@ tsq.value
    limit 50
  ),
  fused as (
    select chunk_id, sum(score) as fused_score, string_agg(method, '+') as method
    from (
      select chunk_id, 1.0 / (60 + rank_position) as score, 'dense'::text as method
      from dense_ranked
      union all
      select chunk_id, 1.0 / (60 + rank_position) as score, 'keyword'::text as method
      from keyword_ranked
    ) ranked
    group by chunk_id
  )
  select
    f.chunk_id,
    f.document_id,
    f.source_ref,
    f.source_url,
    f.title,
    f.doc_category,
    f.document_type,
    f.allowed_use,
    f.authority_level,
    f.chunk_text,
    fused.fused_score::double precision as similarity_score,
    ('hybrid:' || fused.method)::text as retrieval_method,
    f.metadata
  from fused
  join filtered f on f.chunk_id = fused.chunk_id
  order by fused.fused_score desc, f.title asc
  limit greatest(match_count, 1);
$$;

