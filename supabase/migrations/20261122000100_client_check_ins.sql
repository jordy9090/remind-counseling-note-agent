-- Client check-ins between sessions (내담자 수시 기록).
-- A counselor invites a client to one case; the client joins with an email account, consents,
-- and records how they are doing. The counselor can only read those records; the client can
-- only write, read and delete their own. No AI processing uses these tables.
--
-- State changes that cross the two parties (accepting an invite, ending a link) go through
-- SECURITY DEFINER functions, so neither side can update a link row directly.
-- Notes are stored as written by the client: they are identifying health information under
-- the client's own consent (consent_version records which text they agreed to).

create table public.client_links (
    id uuid primary key default gen_random_uuid(),
    case_id text not null references public.cases(id) on delete cascade,
    -- The counselor who owns the case (same convention as public.cases.user_id).
    user_id text not null,
    client_user_id uuid references auth.users(id) on delete set null,
    status text not null default 'invited' check (status in ('invited', 'active', 'ended')),
    invite_token_hash text unique check (invite_token_hash is null or invite_token_hash ~ '^[0-9a-f]{64}$'),
    invite_expires_at timestamptz,
    consent_version text check (consent_version is null or char_length(consent_version) between 1 and 40),
    consented_at timestamptz,
    created_at timestamptz not null default now(),
    accepted_at timestamptz,
    ended_at timestamptz,
    ended_by text check (ended_by in ('counselor', 'client')),
    check (status <> 'invited' or (client_user_id is null and invite_token_hash is not null and invite_expires_at is not null)),
    check (status <> 'active' or (client_user_id is not null and consented_at is not null and invite_token_hash is null)),
    check (status <> 'ended' or (ended_at is not null and invite_token_hash is null))
);

-- One open (invited or active) link per case, and one active link per client account.
create unique index client_links_one_open_per_case on public.client_links(case_id) where status <> 'ended';
create unique index client_links_one_active_per_client on public.client_links(client_user_id) where status = 'active';
create index client_links_user_id on public.client_links(user_id);

alter table public.client_links enable row level security;
revoke all on public.client_links from anon;
revoke update, delete on public.client_links from authenticated;
grant select, insert on public.client_links to authenticated;

create policy client_links_counselor_select on public.client_links
    for select to authenticated using (user_id = (select auth.uid())::text);
create policy client_links_client_select on public.client_links
    for select to authenticated using (client_user_id = (select auth.uid()));
-- A counselor creates an invite only for a case they own.
create policy client_links_counselor_invite on public.client_links
    for insert to authenticated
    with check (
        user_id = (select auth.uid())::text
        and status = 'invited'
        and client_user_id is null
        and exists (select 1 from public.cases c where c.id = case_id and c.user_id = (select auth.uid())::text)
    );

create table public.client_check_ins (
    id uuid primary key default gen_random_uuid(),
    link_id uuid not null references public.client_links(id) on delete cascade,
    client_user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    mood smallint not null check (mood between 0 and 10),
    emotions text[] not null default '{}' check (
        cardinality(emotions) <= 8
        and emotions <@ array['불안', '슬픔', '화남', '무기력', '외로움', '긴장', '피곤함', '괜찮음', '편안함', '기쁨']::text[]
    ),
    note text not null default '' check (char_length(note) <= 1000),
    created_at timestamptz not null default now()
);

create index client_check_ins_link_created on public.client_check_ins(link_id, created_at desc);
create index client_check_ins_client on public.client_check_ins(client_user_id);

alter table public.client_check_ins enable row level security;
revoke all on public.client_check_ins from anon;
revoke update on public.client_check_ins from authenticated;
grant select, insert, delete on public.client_check_ins to authenticated;

create policy client_check_ins_client_select on public.client_check_ins
    for select to authenticated using (client_user_id = (select auth.uid()));
create policy client_check_ins_client_insert on public.client_check_ins
    for insert to authenticated
    with check (
        client_user_id = (select auth.uid())
        and exists (
            select 1 from public.client_links l
            where l.id = link_id and l.client_user_id = (select auth.uid()) and l.status = 'active'
        )
    );
create policy client_check_ins_client_delete on public.client_check_ins
    for delete to authenticated using (client_user_id = (select auth.uid()));
-- The counselor reads entries of links on their own cases; there is no counselor write policy.
create policy client_check_ins_counselor_select on public.client_check_ins
    for select to authenticated
    using (exists (select 1 from public.client_links l where l.id = link_id and l.user_id = (select auth.uid())::text));

-- Enrolled beta cases: no new invite or link change once a case is withdrawn, expired or erased.
-- Erasure deletes the case row, and the foreign keys remove its links and check-ins.
create trigger beta_case_write before insert or update on public.client_links
    for each row execute function beta_retention.check_write();

-- The API passes the SHA-256 of the invite token; the token itself is never stored.
create function public.accept_client_invite(p_token_hash text, p_consent_version text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
    v_user uuid := auth.uid();
    v_link public.client_links;
begin
    if v_user is null then
        raise exception 'Login required' using errcode = '28000';
    end if;
    if p_consent_version is null or char_length(p_consent_version) not between 1 and 40 then
        raise exception 'Consent is required' using errcode = '22023';
    end if;
    -- Counselor accounts keep their counselor role; a client joins with a separate account.
    if exists (select 1 from public.cases where user_id = v_user::text) then
        raise exception 'A counselor account cannot join as a client' using errcode = '42501';
    end if;
    if exists (select 1 from public.client_links where client_user_id = v_user and status = 'active') then
        raise exception 'This account is already linked' using errcode = '23505';
    end if;
    select * into v_link from public.client_links where invite_token_hash = p_token_hash for update;
    if not found or v_link.status <> 'invited' or v_link.invite_expires_at <= now()
       or v_link.user_id = v_user::text then
        raise exception 'Invite is not valid' using errcode = '22023';
    end if;
    update public.client_links
        set status = 'active', client_user_id = v_user, invite_token_hash = null,
            consent_version = p_consent_version, consented_at = now(), accepted_at = now()
        where id = v_link.id;
    -- The API reads this from the verified user record to keep client accounts out of counselor routes.
    update auth.users
        set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"remind_role": "client"}'::jsonb
        where id = v_user;
    return v_link.id;
end $$;

-- Either party ends a link; an unused invite is revoked the same way. Entries are kept until the
-- client deletes them or the case is deleted.
create function public.end_client_link(p_link_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
    v_user uuid := auth.uid();
begin
    if v_user is null then
        raise exception 'Login required' using errcode = '28000';
    end if;
    update public.client_links
        set status = 'ended', ended_at = now(), invite_token_hash = null,
            ended_by = case when user_id = v_user::text then 'counselor' else 'client' end
        where id = p_link_id and status <> 'ended'
          and (user_id = v_user::text or client_user_id = v_user);
    if not found then
        raise exception 'Link not found' using errcode = 'P0002';
    end if;
end $$;

revoke all on function public.accept_client_invite(text, text) from public, anon;
revoke all on function public.end_client_link(uuid) from public, anon;
grant execute on function public.accept_client_invite(text, text) to authenticated;
grant execute on function public.end_client_link(uuid) to authenticated;
