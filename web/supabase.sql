-- フィーバー三麻 ランキング用のテーブル。
-- Supabase の SQL Editor に貼り付けて1回だけ実行する。

create table if not exists public.results (
  id bigint generated always as identity primary key,
  name text not null check (char_length(name) between 1 and 20),
  raw_score integer not null,
  final_score integer not null,
  rank smallint not null check (rank between 1 and 3),
  opponents text not null default '',
  version text,
  created_at timestamptz not null default now()
);

-- 誰でも「読む」「追加する」だけできる。変更・削除はできない（管理画面からのみ）。
alter table public.results enable row level security;

drop policy if exists "results are readable" on public.results;
create policy "results are readable" on public.results for select using (true);

drop policy if exists "results are insertable" on public.results;
create policy "results are insertable" on public.results for insert with check (true);

grant select, insert on public.results to anon;

-- 名前ごとの集計（平均・トップ率・対局数・最高素点）
create or replace view public.player_stats
with (security_invoker = true) as
select
  name,
  count(*) as games,
  round(avg(final_score))::integer as avg_final,
  round(100.0 * avg((rank = 1)::int), 1) as top_rate,
  max(raw_score) as best_raw
from public.results
group by name;

grant select on public.player_stats to anon;
