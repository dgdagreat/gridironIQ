-- =====================================================================
-- GridironIQ :: analytical views + indexes (the SQL modeling layer)
-- =====================================================================
-- Applied by the ETL *after* the base tables are loaded. Views encode the core
-- analytical joins so the Python/ML layer and the frontend read from one
-- consistent source of truth.

-- ---------- indexes ----------
CREATE INDEX IF NOT EXISTS idx_pos_spend_season  ON positional_spending(season);
CREATE INDEX IF NOT EXISTS idx_pos_spend_team    ON positional_spending(team);
CREATE INDEX IF NOT EXISTS idx_pyc_season_team   ON player_year_caps(season, team);
CREATE INDEX IF NOT EXISTS idx_features_season   ON spending_features(season);

-- ---------- base modeling table: features + supervised target ----------
DROP VIEW IF EXISTS v_team_season;
CREATE VIEW v_team_season AS
SELECT
    f.*,
    COALESCE(o.sb_appearance, 0) AS sb_appearance,
    COALESCE(o.sb_win, 0)        AS sb_win
FROM spending_features f
LEFT JOIN team_outcomes o
    ON o.season = f.season AND o.team = f.team;

-- ---------- long positional spending tagged with outcomes ----------
DROP VIEW IF EXISTS v_positional_long;
CREATE VIEW v_positional_long AS
SELECT
    s.*,
    COALESCE(o.sb_appearance, 0) AS sb_appearance,
    COALESCE(o.sb_win, 0)        AS sb_win
FROM positional_spending s
LEFT JOIN team_outcomes o
    ON o.season = s.season AND o.team = s.team;

-- ---------- average positional share by era (era-aware baselines) ----------
DROP VIEW IF EXISTS v_positional_era_avg;
CREATE VIEW v_positional_era_avg AS
SELECT
    era,
    pos_group,
    COUNT(*)      AS n_team_seasons,
    AVG(cap_pct)  AS avg_cap_pct
FROM positional_spending
GROUP BY era, pos_group;

-- ---------- the headline: do champions over- or under-index by position? ----------
-- champion_premium > 0  => SB winners historically spend MORE here than average
-- champion_premium < 0  => winners win while spending LESS here (a value position)
DROP VIEW IF EXISTS v_position_success;
CREATE VIEW v_position_success AS
SELECT
    pos_group,
    AVG(cap_pct)                                           AS league_avg_pct,
    AVG(CASE WHEN sb_appearance = 1 THEN cap_pct END)      AS finalist_avg_pct,
    AVG(CASE WHEN sb_win = 1 THEN cap_pct END)             AS champion_avg_pct,
    AVG(CASE WHEN sb_win = 1 THEN cap_pct END) - AVG(cap_pct)
                                                           AS champion_premium,
    -- era-comparable version on the normalized (coverage-adjusted) share
    AVG(cap_pct_norm)                                      AS league_avg_norm,
    AVG(CASE WHEN sb_win = 1 THEN cap_pct_norm END)        AS champion_avg_norm,
    AVG(CASE WHEN sb_win = 1 THEN cap_pct_norm END) - AVG(cap_pct_norm)
                                                           AS champion_premium_norm
FROM v_positional_long
GROUP BY pos_group;
