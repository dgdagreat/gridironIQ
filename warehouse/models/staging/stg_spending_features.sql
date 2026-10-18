-- Wide model matrix: one row per team-season, positional cap shares.
with src as (
    select * from {{ source('raw', 'spending_features') }}
)
select
    season || '-' || team       as team_season_sk,
    cast(season as integer)     as season,
    team,
    era,
    cast(pct_QB   as double)    as pct_qb,
    cast(pct_RB   as double)    as pct_rb,
    cast(pct_WR   as double)    as pct_wr,
    cast(pct_TE   as double)    as pct_te,
    cast(pct_OL   as double)    as pct_ol,
    cast(pct_IDL  as double)    as pct_idl,
    cast(pct_EDGE as double)    as pct_edge,
    cast(pct_LB   as double)    as pct_lb,
    cast(pct_CB   as double)    as pct_cb,
    cast(pct_S    as double)    as pct_s,
    cast(pct_SPEC as double)    as pct_spec,
    cast(total_pct as double)   as total_pct
from src
