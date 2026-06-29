-- 상담 내용(임시저장 초안) 저장 테이블
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 실행하세요.

create table if not exists public.counseling_drafts (
    draft_id       text primary key,
    case_id        text not null,
    session_number integer not null default 0,
    saved_at       timestamptz not null default now(),
    data           jsonb not null,
    created_at     timestamptz not null default now()
);

-- 사례별/최신순 조회 성능용 인덱스
create index if not exists counseling_drafts_case_id_idx
    on public.counseling_drafts (case_id);

create index if not exists counseling_drafts_saved_at_idx
    on public.counseling_drafts (saved_at desc);

-- 백엔드는 service_role 키로 접근하므로 RLS 를 통과합니다.
-- 클라이언트(anon 키)에서 직접 접근을 막으려면 RLS 를 켜 두는 것을 권장합니다.
alter table public.counseling_drafts enable row level security;
