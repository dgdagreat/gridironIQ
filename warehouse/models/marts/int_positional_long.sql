-- Long positional spending tagged with SB outcomes.
-- Rebuild of the SQLite view v_positional_long as a tested model.
with spend as (
    select * from {{ ref('stg_positional_spending') }}
),
outcomes as (
    select * from {{ ref('stg_team_outcomes') }}
)
select
    s.spend_sk,
    s.season,
    s.team,
    s.era,
    s.pos_group,
    s.cap_dollars,
    s.cap_pct,
    s.cap_pct_norm,
    s.n_players,
    coalesce(o.sb_appearance, 0) as sb_appearance,
    coalesce(o.sb_win, 0)        as sb_win,
    -- a season is "finalized" only if it has a played outcome; forward cap
    -- projections carry no SB result and only partial rosters.
    (o.season is not null)       as is_finalized_season
from spend s
left join outcomes o
    on o.season = s.season and o.team = s.team
