-- Ensure counselor-confirmed memory chunks are idempotent per note field.
-- Non-destructive: if duplicate rows already exist, stop and require manual review.

alter table public.case_memory_chunks
  add column if not exists embedding_updated_at timestamptz;

alter table public.retrieval_logs
  add column if not exists embedding_latency_ms integer,
  add column if not exists rpc_latency_ms integer,
  add column if not exists total_latency_ms integer,
  add column if not exists generation_latency_ms integer;

do $$
begin
  if exists (
    select 1
    from public.case_memory_chunks
    where source_note_id is not null
    group by source_note_id, field_type
    having count(*) > 1
  ) then
    raise exception 'Duplicate case_memory_chunks(source_note_id, field_type) rows exist; review before adding unique index.';
  end if;
end $$;

create unique index if not exists uq_case_memory_source_note_field
  on public.case_memory_chunks(source_note_id, field_type);

create index if not exists idx_case_memory_embedding_updated_at
  on public.case_memory_chunks(embedding_updated_at desc);
