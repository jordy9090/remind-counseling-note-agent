-- Per-client person dictionary (인물 사전): a stable label per person and the names, misheard names
-- and relation words that refer to them, so later sessions reuse the same labels.
-- Non-destructive: one column with an empty default and one named check constraint. No data rewrite.
-- Ownership/RLS: the existing user_owns_rows policy on public.cases already covers this column.
-- Note: entries contain names as entered (identifying). They are stored only under the owner's RLS
-- scope, like the client alias; use synthetic data outside of a consented production rollout.

alter table public.cases add column if not exists person_dictionary jsonb not null default '[]'::jsonb;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'cases_person_dictionary_is_array'
  ) then
    alter table public.cases
      add constraint cases_person_dictionary_is_array
      check (jsonb_typeof(person_dictionary) = 'array');
  end if;
end $$;
