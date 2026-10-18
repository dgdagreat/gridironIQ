-- Team x season x position-group cap spending, typed and keyed.
-- Surrogate key lets us test grain (one row per season/team/pos_group)
-- without an external package.
with src as (
    select * from {{ source('raw', 'positional_spending') }}
)
select
    season || '-' || team || '-' || pos_group as spend_sk,
    cast(season as integer)                   as season,
    team,
    era,
    pos_group,
    cast(cap_dollars  as double)              as cap_dollars,
    cast(cap_pct      as double)              as cap_pct,
    cast(cap_pct_norm as double)              as cap_pct_norm,
    cast(cap_pct_ref  as double)              as cap_pct_ref,
    cast(n_players    as integer)             as n_players
from src
