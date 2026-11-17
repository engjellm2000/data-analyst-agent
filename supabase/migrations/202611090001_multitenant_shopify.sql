create extension if not exists pgcrypto;

create table if not exists public.tenants (
    tenant_id uuid primary key default gen_random_uuid(),
    name text not null check (length(name) between 1 and 120),
    created_at timestamptz not null default now()
);

create table if not exists public.tenant_memberships (
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('owner', 'analyst', 'viewer')),
    created_at timestamptz not null default now(),
    primary key (tenant_id, user_id)
);

create table if not exists public.shopify_stores (
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    shop_domain text not null check (shop_domain ~ '^[a-z0-9][a-z0-9-]*\.myshopify\.com$'),
    status text not null default 'connected' check (status in ('connected', 'disconnected')),
    scopes text not null default '',
    currency text,
    installed_at timestamptz not null default now(),
    last_webhook_at timestamptz,
    primary key (tenant_id, shop_domain),
    unique (tenant_id),
    unique (shop_domain)
);

create table if not exists public.shopify_tokens (
    tenant_id uuid not null,
    shop_domain text not null,
    encrypted_access_token text not null,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, shop_domain),
    foreign key (tenant_id, shop_domain)
        references public.shopify_stores(tenant_id, shop_domain) on delete cascade
);

create table if not exists public.orders (
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    order_id text not null,
    order_date date not null,
    channel text,
    category text,
    device text,
    region text,
    warehouse text,
    units integer not null check (units >= 0),
    net_revenue double precision not null,
    discount_rate double precision,
    delivery_days double precision,
    returned boolean,
    marketing_spend double precision,
    customer_id text,
    order_status text not null default 'active',
    currency text,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, order_id)
);
create index if not exists orders_tenant_date_idx on public.orders (tenant_id, order_date);

create table if not exists public.dataset_metadata (
    tenant_id uuid primary key references public.tenants(tenant_id) on delete cascade,
    metadata_json jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists public.investigations (
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    investigation_id uuid not null default gen_random_uuid(),
    run_at timestamptz not null default now(),
    window_days integer not null check (window_days in (7, 14, 30, 60, 90)),
    result_json jsonb not null,
    primary key (tenant_id, investigation_id)
);
create index if not exists investigations_tenant_window_run_idx
    on public.investigations (tenant_id, window_days, run_at desc);

create table if not exists public.shopify_oauth_states (
    state_hash text primary key,
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    shop_domain text not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now()
);

create table if not exists public.shopify_webhook_receipts (
    event_id text primary key,
    tenant_id uuid not null references public.tenants(tenant_id) on delete cascade,
    shop_domain text not null,
    topic text not null,
    received_at timestamptz not null default now()
);

alter table public.tenants enable row level security;
alter table public.tenant_memberships enable row level security;
alter table public.shopify_stores enable row level security;
alter table public.shopify_tokens enable row level security;
alter table public.orders enable row level security;
alter table public.dataset_metadata enable row level security;
alter table public.investigations enable row level security;
alter table public.shopify_oauth_states enable row level security;
alter table public.shopify_webhook_receipts enable row level security;

drop policy if exists tenant_member_reads_tenant on public.tenants;
create policy tenant_member_reads_tenant on public.tenants
    for select to authenticated
    using (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = tenants.tenant_id and m.user_id = auth.uid()
    ));

drop policy if exists user_reads_own_memberships on public.tenant_memberships;
create policy user_reads_own_memberships on public.tenant_memberships
    for select to authenticated using (user_id = auth.uid());

drop policy if exists tenant_members_read_store_status on public.shopify_stores;
create policy tenant_members_read_store_status on public.shopify_stores
    for select to authenticated
    using (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = shopify_stores.tenant_id and m.user_id = auth.uid()
    ));

drop policy if exists tenant_members_read_orders on public.orders;
create policy tenant_members_read_orders on public.orders
    for select to authenticated
    using (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = orders.tenant_id and m.user_id = auth.uid()
    ));

drop policy if exists tenant_members_read_metadata on public.dataset_metadata;
create policy tenant_members_read_metadata on public.dataset_metadata
    for select to authenticated
    using (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = dataset_metadata.tenant_id and m.user_id = auth.uid()
    ));

drop policy if exists tenant_members_read_investigations on public.investigations;
create policy tenant_members_read_investigations on public.investigations
    for select to authenticated
    using (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = investigations.tenant_id and m.user_id = auth.uid()
    ));
drop policy if exists tenant_members_create_investigations on public.investigations;
create policy tenant_members_create_investigations on public.investigations
    for insert to authenticated
    with check (exists (
        select 1 from public.tenant_memberships m
        where m.tenant_id = investigations.tenant_id and m.user_id = auth.uid()
    ));

revoke all on public.tenants, public.tenant_memberships, public.shopify_stores,
    public.shopify_tokens, public.orders, public.dataset_metadata, public.investigations,
    public.shopify_oauth_states, public.shopify_webhook_receipts from anon;
grant select on public.tenants, public.tenant_memberships, public.shopify_stores,
    public.orders, public.dataset_metadata, public.investigations to authenticated;
grant insert on public.investigations to authenticated;
revoke all on public.shopify_tokens, public.shopify_oauth_states,
    public.shopify_webhook_receipts from authenticated;

-- Backend uses the authenticated Postgres role and the verified Supabase JWT
-- claims; webhook/token operations use server-only privileged connections.
grant usage on schema public to authenticated;
