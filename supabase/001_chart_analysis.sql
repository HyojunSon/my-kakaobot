-- Supabase Dashboard > SQL Editor > New query > Run
-- Creates storage and permissions only. Does not upload local drawings.
begin;

create table if not exists public.hts_editors (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists public.chart_analysis (
    symbol text primary key check (symbol ~ '^[0-9A-Z]{6}$' or symbol in ('KOSPI', 'KOSDAQ')),
    name text not null default '',
    drawings jsonb not null default '[]'::jsonb check (jsonb_typeof(drawings) = 'array'),
    revision bigint not null default 1 check (revision > 0),
    updated_at timestamptz not null default now(),
    updated_by uuid references auth.users(id) on delete set null
);

create or replace function public.stamp_chart_analysis()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    new.updated_by := auth.uid();
    if tg_op = 'UPDATE' then
        new.revision := old.revision + 1;
    else
        new.revision := 1;
    end if;
    return new;
end;
$$;

drop trigger if exists stamp_chart_analysis on public.chart_analysis;
create trigger stamp_chart_analysis
before insert or update on public.chart_analysis
for each row execute function public.stamp_chart_analysis();

alter table public.hts_editors enable row level security;
alter table public.chart_analysis enable row level security;

revoke all on public.hts_editors from anon, authenticated;
grant select on public.hts_editors to authenticated;
revoke all on public.chart_analysis from anon, authenticated;
grant select, insert, update on public.chart_analysis to authenticated;
grant select on public.chart_analysis to service_role;

drop policy if exists hts_editor_self on public.hts_editors;
create policy hts_editor_self on public.hts_editors
for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists chart_editor_select on public.chart_analysis;
create policy chart_editor_select on public.chart_analysis
for select to authenticated using (
    exists (select 1 from public.hts_editors where user_id = (select auth.uid()))
);

drop policy if exists chart_editor_insert on public.chart_analysis;
create policy chart_editor_insert on public.chart_analysis
for insert to authenticated with check (
    exists (select 1 from public.hts_editors where user_id = (select auth.uid()))
);

drop policy if exists chart_editor_update on public.chart_analysis;
create policy chart_editor_update on public.chart_analysis
for update to authenticated using (
    exists (select 1 from public.hts_editors where user_id = (select auth.uid()))
) with check (
    exists (select 1 from public.hts_editors where user_id = (select auth.uid()))
);

-- Clear a chart by uploading drawings=[]; do not delete its row.
comment on table public.chart_analysis is
    'Shared manual HTS drawings. One row per symbol; never store temporary automatic suggestions or private memos.';

commit;

-- Confirm both tables exist and RLS is enabled.
select tablename, rowsecurity
from pg_tables
where schemaname = 'public' and tablename in ('chart_analysis', 'hts_editors')
order by tablename;
