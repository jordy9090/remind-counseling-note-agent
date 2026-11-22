-- Read current operator-managed permissions, not stale JWT/user-editable metadata.
-- This does not create a consent or authorize an existing beta enrollment.
create schema processing_authorization;
revoke all on schema processing_authorization from public, anon, authenticated, service_role;

create function processing_authorization.check_permission(
    p_case_id text, p_policy_version text, p_purpose text, p_provider text
) returns boolean
language plpgsql security definer set search_path = '' as $$
declare
    owner_id uuid := auth.uid();
    enrollment beta_retention.enrollments;
    permission jsonb;
    now_epoch numeric := extract(epoch from clock_timestamp());
begin
    if owner_id is null or p_policy_version is null or p_policy_version = ''
       or length(p_policy_version) > 80 or p_purpose is null or p_provider is null then
        return false;
    end if;
    select * into enrollment from beta_retention.enrollments e
      where e.case_id = p_case_id and e.owner_id = owner_id
        and e.withdrawn_at is null and e.erased_at is null
        and e.signed_at <= clock_timestamp() and e.ends_at > clock_timestamp();
    if not found then return false; end if;
    select u.raw_app_meta_data -> 'remind_processing_authorizations' -> p_case_id
      into permission from auth.users u where u.id = owner_id;
    if jsonb_typeof(permission) is distinct from 'object'
       or permission ->> 'status' is distinct from 'active'
       or permission ->> 'policy_version' is distinct from p_policy_version
       or permission ->> 'receipt' is distinct from enrollment.receipt::text
       or jsonb_typeof(permission -> 'not_before') is distinct from 'number'
       or jsonb_typeof(permission -> 'expires_at') is distinct from 'number'
       or jsonb_typeof(permission -> 'permissions' -> p_purpose) is distinct from 'array' then
        return false;
    end if;
    return (permission ->> 'not_before')::numeric >= extract(epoch from enrollment.signed_at)
       and (permission ->> 'not_before')::numeric <= now_epoch
       and (permission ->> 'expires_at')::numeric > now_epoch
       and (permission ->> 'expires_at')::numeric <= extract(epoch from enrollment.ends_at)
       and (permission -> 'permissions' -> p_purpose) @> jsonb_build_array(p_provider);
end $$;
revoke all on function processing_authorization.check_permission(text,text,text,text)
    from public, anon, authenticated, service_role;
-- The private helper exposes only the caller's Boolean decision; tables stay revoked.
grant usage on schema processing_authorization to authenticated;
grant execute on function processing_authorization.check_permission(text,text,text,text) to authenticated;

create function public.case_processing_allowed(
    p_case_id text, p_policy_version text, p_purpose text, p_provider text
) returns boolean
language sql security invoker set search_path = '' as $$
    select processing_authorization.check_permission(p_case_id, p_policy_version, p_purpose, p_provider)
$$;
revoke all on function public.case_processing_allowed(text,text,text,text)
    from public, anon, authenticated, service_role;
grant execute on function public.case_processing_allowed(text,text,text,text) to authenticated;

-- Rollback only after reverting the corresponding API: drop the public wrapper,
-- drop the private helper and its new schema. No rows change.
