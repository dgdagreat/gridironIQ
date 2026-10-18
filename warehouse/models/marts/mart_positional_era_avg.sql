-- Average positional cap share by era (era-aware baselines).
-- Rebuild of the SQLite view v_positional_era_avg. Finalized seasons only.
with long as (
    select * from {{ ref('int_positional_long') }}
    where is_finalized_season
)
select
    era,
    pos_group,
    count(*)     as n_team_seasons,
    avg(cap_pct) as avg_cap_pct
from long
group by era, pos_group
