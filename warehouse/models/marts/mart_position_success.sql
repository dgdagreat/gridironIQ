-- THE HEADLINE: do champions over- or under-index by position?
--   champion_premium > 0  => SB winners spend MORE here than league average
--   champion_premium < 0  => winners win while spending LESS (a value position)
-- Rebuild of the SQLite view v_position_success.
-- Only finalized seasons count — forward cap projections have no SB result and
-- only partial rosters, which would pollute the premium.
with long as (
    select * from {{ ref('int_positional_long') }}
    where is_finalized_season
)
select
    pos_group,
    avg(cap_pct)                                        as league_avg_pct,
    avg(case when sb_appearance = 1 then cap_pct end)   as finalist_avg_pct,
    avg(case when sb_win = 1 then cap_pct end)          as champion_avg_pct,
    avg(case when sb_win = 1 then cap_pct end)
        - avg(cap_pct)                                  as champion_premium,
    avg(cap_pct_norm)                                   as league_avg_norm,
    avg(case when sb_win = 1 then cap_pct_norm end)     as champion_avg_norm,
    avg(case when sb_win = 1 then cap_pct_norm end)
        - avg(cap_pct_norm)                             as champion_premium_norm
from long
group by pos_group
