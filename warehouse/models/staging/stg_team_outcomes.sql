-- Tidy team-season outcomes: the supervised target for the SB model.
with src as (
    select * from {{ source('raw', 'team_outcomes') }}
)
select
    season || '-' || team               as team_season_sk,
    cast(season as integer)             as season,
    team,
    cast(sb_appearance as integer)      as sb_appearance,
    cast(sb_win        as integer)      as sb_win
from src
