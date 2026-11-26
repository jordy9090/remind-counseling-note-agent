-- Installed only in the runner's newly created network-isolated database.
-- Explicit administrator setup; never grants itself to an application role.
create schema poc_permissions;
revoke all on schema poc_permissions from public, anon, authenticated, service_role;
create function poc_permissions.authorize(p_owner uuid, p_case text) returns void
language plpgsql security invoker set search_path = '' as $$
declare receipt_id uuid := substring(p_case from 9)::uuid;
begin
    insert into processing_authorization.policy values(true, 'synthetic-v1') on conflict do nothing;
    insert into beta_retention.enrollments(receipt,case_id,owner_id,signed_at,ends_at)
      values(receipt_id,p_case,p_owner,clock_timestamp()-interval '1 hour',clock_timestamp()+interval '6 days')
      on conflict do nothing;
    update auth.users set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) ||
      jsonb_build_object('remind_processing_authorizations',
        coalesce(raw_app_meta_data->'remind_processing_authorizations', '{}'::jsonb) ||
        jsonb_build_object(p_case, jsonb_build_object(
          'status','active','policy_version','synthetic-v1','receipt',receipt_id::text,
          'not_before',extract(epoch from clock_timestamp()),
          'expires_at',extract(epoch from clock_timestamp()+interval '1 hour'),
          'permissions',jsonb_build_object('storage',jsonb_build_array('supabase'),
                                          'generate',jsonb_build_array('openai')))))
      where id=p_owner;
end $$;
revoke all on function poc_permissions.authorize(uuid,text) from public, anon, authenticated, service_role;
