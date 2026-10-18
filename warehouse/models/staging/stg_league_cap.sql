-- Per-team league salary cap by season (denominator for every share).
with src as (
    select * from {{ source('raw', 'league_cap') }}
)
select
    cast(season as integer)     as season,
    cast(league_cap as bigint)  as league_cap,
    era,
    milestone
from src
