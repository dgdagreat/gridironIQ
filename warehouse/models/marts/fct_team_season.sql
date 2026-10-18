-- Model-ready fact: wide positional features + supervised SB target.
-- Rebuild of the SQLite view v_team_season. One row per team-season.
with features as (
    select * from {{ ref('stg_spending_features') }}
),
outcomes as (
    select * from {{ ref('stg_team_outcomes') }}
)
select
    f.*,
    coalesce(o.sb_appearance, 0) as sb_appearance,
    coalesce(o.sb_win, 0)        as sb_win
from features f
left join outcomes o
    on o.season = f.season and o.team = f.team
