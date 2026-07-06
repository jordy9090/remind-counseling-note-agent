-- Re:mind V1 Supabase schema
-- Intended for synthetic/demo counseling documentation data until auth, RLS,
-- retention, and audit policies are finalized.

create extension if not exists pgcrypto;

create table if not exists cases (
  id text primary key,
  case_alias text,
  counselor_id text,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table if not exists sessions (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references cases(id) on delete cascade,
  session_number integer not null,
  session_date date,
  session_title text,
  -- Kept nullable by design. The app stores NULL unless SAVE_RAW_INPUT=1.
  -- Do not store real counselor memo/transcript text before auth, RLS,
  -- audit logging, explicit consent, and retention policy are in place.
  raw_input_text text,
  sanitized_input_text text,
  created_at timestamptz not null default now(),
  unique(case_id, session_number)
);

create table if not exists generated_notes (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references cases(id) on delete cascade,
  session_id uuid references sessions(id) on delete cascade,
  note_type text not null default 'session_note',
  draft_json jsonb not null default '{}'::jsonb,
  confirmed_json jsonb not null default '{}'::jsonb,
  counselor_edited boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists evidence_items (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references cases(id) on delete cascade,
  session_id uuid references sessions(id) on delete cascade,
  source_type text not null default '',
  source_ref text not null default '',
  source_text text not null default '',
  start_char integer,
  end_char integer,
  linked_field text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists verification_reports (
  id uuid primary key default gen_random_uuid(),
  case_id text not null references cases(id) on delete cascade,
  session_id uuid references sessions(id) on delete cascade,
  note_id uuid references generated_notes(id) on delete cascade,
  report_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists kb_documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source_type text not null default '',
  authority_level text not null default 'internal_demo',
  doc_category text not null check (
    doc_category in (
      'document_template',
      'ethics_rule',
      'privacy_rule',
      'security_rule',
      'writing_example',
      'internal_policy'
    )
  ),
  source_url text,
  effective_date date,
  allowed_use text not null default 'verification_and_documentation_support_only',
  created_at timestamptz not null default now()
);

create table if not exists kb_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references kb_documents(id) on delete cascade,
  chunk_text text not null,
  chunk_type text not null default 'guideline',
  metadata_json jsonb not null default '{}'::jsonb
  -- V2 TODO: enable pgvector after access isolation and retention policy.
  -- embedding vector(1536)
);

create index if not exists idx_sessions_case_recent
  on sessions(case_id, session_number desc, created_at desc);

create index if not exists idx_generated_notes_session_recent
  on generated_notes(session_id, created_at desc);

create index if not exists idx_evidence_items_session
  on evidence_items(session_id, linked_field);

create index if not exists idx_kb_documents_category
  on kb_documents(doc_category, source_type);

create index if not exists idx_kb_chunks_document
  on kb_chunks(document_id, chunk_type);
