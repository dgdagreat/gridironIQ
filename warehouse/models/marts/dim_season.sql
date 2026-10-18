-- Season dimension: league cap, era, rule milestone, and whether the season
-- has finalized outcomes (played) vs. is a forward cap projection.
with cap as (
    select * from {{ ref('stg_league_cap') }}
),
played as (
    select distinct season from {{ ref('stg_team_outcomes') }}
)
select
    c.season,
    c.league_cap,
    c.era,
    c.milestone,
    (p.season is not null) as is_finalized_season
from cap c
left join played p on p.season = c.season
