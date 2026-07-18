-- Re:mind baseline schema.
-- Non-destructive: creates missing tables/indexes only.
-- Intended for demo/synthetic counseling documentation data until auth, RLS,
-- retention, and audit policies are finalized.

create extension if not exists pgcrypto;

create table if not exists public.cases (
  id text primary key,
  case_alias text,
  counselor_id text,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table if not exists public.sessions (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references public.cases(id) on delete cascade,
  session_number integer not null,
  session_date date,
  session_title text,
  raw_input_text text,
  sanitized_input_text text,
  created_at timestamptz not null default now(),
  unique(case_id, session_number)
);

create table if not exists public.generated_notes (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete cascade,
  note_type text not null default 'session_note',
  draft_json jsonb not null default '{}'::jsonb,
  confirmed_json jsonb not null default '{}'::jsonb,
  counselor_edited boolean not null default false,
  confirmation_status text not null default 'draft',
  confirmed_at timestamptz,
  confirmed_by text,
  source_note_id uuid references public.generated_notes(id) on delete set null,
  memory_indexed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.evidence_items (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete cascade,
  source_type text not null default '',
  source_ref text not null default '',
  source_text text not null default '',
  start_char integer,
  end_char integer,
  linked_field text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.verification_reports (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references public.cases(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete cascade,
  note_id uuid references public.generated_notes(id) on delete cascade,
  report_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.kb_documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source_type text not null default '',
  authority_level text not null default 'internal_demo',
  doc_category text not null,
  source_url text,
  effective_date date,
  allowed_use text not null default 'verification_and_documentation_support_only',
  created_at timestamptz not null default now()
);

create table if not exists public.kb_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.kb_documents(id) on delete cascade,
  chunk_text text not null,
  chunk_type text not null default 'guideline',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.counseling_drafts (
  draft_id text primary key,
  case_id text not null,
  session_number integer not null default 0,
  saved_at timestamptz not null default now(),
  data jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_sessions_case_recent
  on public.sessions(case_id, session_number desc, created_at desc);

create index if not exists idx_generated_notes_session_recent
  on public.generated_notes(session_id, created_at desc);

create index if not exists idx_evidence_items_session
  on public.evidence_items(session_id, linked_field);

create index if not exists idx_kb_documents_category
  on public.kb_documents(doc_category, source_type);

create index if not exists idx_kb_chunks_document
  on public.kb_chunks(document_id, chunk_type);

create index if not exists counseling_drafts_case_id_idx
  on public.counseling_drafts(case_id);

create index if not exists counseling_drafts_saved_at_idx
  on public.counseling_drafts(saved_at desc);
