-- Minimal Supabase SQL identity contract in a new, empty test database.
-- These are database roles/claim helpers, not real Auth accounts or signed JWTs.
create role anon nologin nosuperuser nobypassrls;
create role authenticated nologin nosuperuser nobypassrls;
create role service_role nologin nosuperuser bypassrls;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
create function auth.role() returns text language sql stable as $$
  select nullif(current_setting('request.jwt.claim.role', true), '')
$$;
grant usage on schema public, auth to anon, authenticated, service_role;
-- Match platform schema access, without supplying table grants or policies.
create schema extensions;
grant usage on schema extensions to anon, authenticated, service_role;
