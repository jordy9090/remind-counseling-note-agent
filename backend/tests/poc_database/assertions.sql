-- Installed within the fixture transaction and rolled back with its rows.
create schema poc_test;
create table poc_test.results (label text primary key, passed boolean not null, diagnostic text not null);
grant usage on schema poc_test to anon, authenticated, service_role;
grant insert, select on poc_test.results to anon, authenticated, service_role;

-- SECURITY INVOKER is essential: statements must execute with real caller RLS.
create function poc_test.count_is(statement text, expected bigint, label text) returns void
language plpgsql security invoker as $$
declare actual bigint;
begin
  begin
    execute statement into strict actual;
    insert into poc_test.results values (label, actual = expected,
      case when actual = expected then 'ok' else 'unexpected row count' end);
  exception when others then
    insert into poc_test.results values (label, false, 'SQLSTATE ' || sqlstate);
  end;
end $$;

create function poc_test.denied(statement text, label text, allowed text[] default array['42501']) returns void
language plpgsql security invoker as $$
declare code text;
begin
  begin
    execute statement;
    -- Roll back a successful attack probe instead of contaminating later tests.
    raise exception using errcode = 'P9001', message = 'probe succeeded';
  exception when others then
    code := sqlstate;
  end;
  insert into poc_test.results values (label, code = any(allowed),
    case when code = any(allowed) then 'ok' when code = 'P9001' then 'unexpectedly allowed' else 'SQLSTATE ' || code end);
end $$;

create function poc_test.truth(statement text, label text) returns void
language plpgsql security invoker as $$
declare actual boolean;
begin
  begin
    execute statement into strict actual;
    insert into poc_test.results values (label, coalesce(actual, false),
      case when actual then 'ok' else 'predicate false' end);
  exception when others then
    insert into poc_test.results values (label, false, 'SQLSTATE ' || sqlstate);
  end;
end $$;
