-- Client profile fields on cases (내담자 프로필: 나이·성별·직업·결혼 상태·가족 구성·연락처·특이사항).
-- Non-destructive: nullable columns and one named check constraint only. No data rewrite.
-- Ownership/RLS: the existing user_owns_rows policy on public.cases already covers these columns.
-- Note: client_phone / client_email are contact PII. They are stored only under the owner's RLS
-- scope; use synthetic data outside of a consented production rollout.

alter table public.cases add column if not exists client_age integer;
alter table public.cases add column if not exists client_gender text;
alter table public.cases add column if not exists client_occupation text;
alter table public.cases add column if not exists marital_status text;
alter table public.cases add column if not exists family_composition text;
alter table public.cases add column if not exists client_phone text;
alter table public.cases add column if not exists client_email text;
alter table public.cases add column if not exists client_notes text;
alter table public.cases add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'cases_client_age_range'
  ) then
    alter table public.cases
      add constraint cases_client_age_range
      check (client_age is null or (client_age >= 0 and client_age <= 150));
  end if;
end $$;
