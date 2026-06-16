-- =====================================================================
-- GridironIQ :: canonical data model (Boardroom / cap layer)
-- =====================================================================
-- The ETL drops + recreates these tables, then bulk-loads the matching
-- DataFrames (column names align 1:1 with the ingestion output). SQLite uses
-- dynamic typing, so affinities below document intent rather than enforce it.
-- Analytical VIEWs that sit on top of these tables live in 02_views.sql.

-- ----- League salary cap, per season (the denominator for every share) -----
DROP TABLE IF EXISTS league_cap;
CREATE TABLE league_cap (
    season      INTEGER PRIMARY KEY,
    league_cap  INTEGER,            -- per-team cap in USD; NULL in uncapped 2010
    era         TEXT,               -- segmentation bucket
    milestone   TEXT                -- rule/CBA change first effective this season
);

-- ----- Super Bowl participants by season (human-readable reference) -----
DROP TABLE IF EXISTS super_bowls;
CREATE TABLE super_bowls (
    season  INTEGER PRIMARY KEY,
    winner  TEXT,                   -- canonical franchise code
    loser   TEXT
);

-- ----- Tidy team-season outcomes: the supervised target -----
DROP TABLE IF EXISTS team_outcomes;
CREATE TABLE team_outcomes (
    season         INTEGER,
    team           TEXT,
    sb_appearance  INTEGER,         -- 1 if reached the Super Bowl
    sb_win         INTEGER,         -- 1 if won it
    PRIMARY KEY (season, team)
);

-- ----- Player x season cap charges (exploded contract detail) -----
DROP TABLE IF EXISTS player_year_caps;
CREATE TABLE player_year_caps (
    otc_id       TEXT,
    player       TEXT,
    position     TEXT,              -- raw OTC/roster label
    season       INTEGER,
    team         TEXT,              -- canonical franchise (per-season attribution)
    cap_number   REAL,             -- cap charge in USD
    cap_percent  REAL              -- share of that season's league cap (0..1)
);

-- ----- Team x season x position-group spending (long/tidy) -----
DROP TABLE IF EXISTS positional_spending;
CREATE TABLE positional_spending (
    season       INTEGER,
    team         TEXT,
    era          TEXT,
    pos_group    TEXT,              -- QB, RB, WR, TE, OL, IDL, EDGE, LB, CB, S, SPEC, UNK
    cap_dollars  REAL,
    cap_pct      REAL,             -- sum of player cap shares vs league cap (primary)
    cap_pct_norm REAL,             -- share of the team's accounted cap (era-comparable)
    cap_pct_ref  REAL,             -- cap_dollars / league_cap (cross-check)
    n_players    INTEGER,
    PRIMARY KEY (season, team, pos_group)
);

-- ----- Model-ready wide matrix: one row per team-season -----
DROP TABLE IF EXISTS spending_features;
CREATE TABLE spending_features (
    season    INTEGER,
    team      TEXT,
    era       TEXT,
    pct_QB    REAL,
    pct_RB    REAL,
    pct_WR    REAL,
    pct_TE    REAL,
    pct_OL    REAL,
    pct_IDL   REAL,
    pct_EDGE  REAL,
    pct_LB    REAL,
    pct_CB    REAL,
    pct_S     REAL,
    pct_SPEC  REAL,
    total_pct REAL,
    PRIMARY KEY (season, team)
);
