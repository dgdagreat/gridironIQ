"""
Player value: a learned, week-to-week forecast of a player's production.

The in-season talent blend in :mod:`roster_strength` weights box-score signals by
hand. This learns those weights instead: a gradient-boosted model trained on past
seasons to predict a player's **rest-of-season production** from his form so far —
and it confirms the intuition that *making big plays* matters, with explosive-play
rate landing among the top predictors (above EPA, TDs and CPOE).

    build_training_frame()  weekly stats, past seasons  -> (features, label) rows
    train_value_model()     fit + CV (R²/MAE) + permutation importance -> ValueReport
    predict_values()        current season through week k -> per-player value score

Scope: offensive skill (QB/RB/WR/TE), whose value has a clean observed label
(fantasy points/game). Defense needs its own target (EPA-allowed / defensive value)
and is left for a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, cross_val_score

from gridiron.ingestion.rosters import load_weekly_stats

#: Positions with a clean fantasy-production label.
SKILL_POS = ("QB", "RB", "WR", "TE")
#: Seasons used to train, and the week cutoffs that become training samples.
TRAIN_SEASONS = (2023, 2024, 2025)
CUTOFFS = (4, 6, 8, 10, 12)
#: A sample needs this many games before and after the cutoff to be usable.
MIN_GAMES_EACH_SIDE = 3
#: Model features (per-game, cumulative through the cutoff week). ``expl_g`` is the
#: highlight-play rate; ``pos`` is one-hot encoded.
NUMERIC_FEATURES = ["k", "gp", "epa_g", "yds_g", "td_g", "expl_g",
                    "use_g", "fppr_g", "cpoe", "wopr"]


@dataclass
class ValueReport:
    """Result of :func:`train_value_model`."""
    n_samples: int
    cv_r2_mean: float
    cv_r2_std: float
    cv_mae: float
    baseline_r2: float      # naive "rest-of-season = recent form"
    feature_importance: list[tuple[str, float]]
    model: HistGradientBoostingRegressor = field(repr=False)
    feature_cols: list[str] = field(repr=False, default_factory=list)


def _f(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df.get(col), errors="coerce").fillna(0.0)


def _weekly_skill(seasons) -> pd.DataFrame:
    """Regular-season weekly rows for skill players, with derived per-game inputs."""
    frames = []
    for yr in seasons:
        w = load_weekly_stats(yr)
        w = w[w.get("season_type", pd.Series("REG", index=w.index)).eq("REG")]
        w = w[w["position"].isin(SKILL_POS)].copy()
        w["_season"] = yr
        frames.append(w)
    s = pd.concat(frames, ignore_index=True)
    s["epa"] = _f(s, "passing_epa") + _f(s, "rushing_epa") + _f(s, "receiving_epa")
    s["yds"] = _f(s, "passing_yards") + _f(s, "rushing_yards") + _f(s, "receiving_yards")
    s["tds"] = _f(s, "passing_tds") + _f(s, "rushing_tds") + _f(s, "receiving_tds")
    # highlight / explosive plays: 40+ pass, 20+/40+ rush, 20+/40+ receiving
    s["expl"] = (_f(s, "passing_40") + _f(s, "rushing_20") + _f(s, "rushing_40")
                 + _f(s, "receiving_20") + _f(s, "receiving_40"))
    s["use"] = _f(s, "attempts") + _f(s, "carries") + _f(s, "targets")
    s["fppr"] = _f(s, "fantasy_points_ppr")
    s["cpoe_"] = _f(s, "passing_cpoe")
    s["wopr_"] = _f(s, "wopr")
    return s


def _features_through_k(past: pd.DataFrame, pos: str, k: int) -> dict:
    gp = len(past)
    return dict(pos=pos, k=k, gp=gp,
                epa_g=past.epa.sum() / gp, yds_g=past.yds.sum() / gp,
                td_g=past.tds.sum() / gp, expl_g=past.expl.sum() / gp,
                use_g=past.use.sum() / gp, fppr_g=past.fppr.sum() / gp,
                cpoe=past.cpoe_.mean(), wopr=past.wopr_.mean())


def build_training_frame(seasons=TRAIN_SEASONS, cutoffs=CUTOFFS) -> pd.DataFrame:
    """One row per (player, season, cutoff): features through week k + the label
    ``y`` = mean fantasy points/game over the rest of that season."""
    s = _weekly_skill(seasons)
    rows: list[dict] = []
    for (_pid, _season, pos), g in s.groupby(["player_id", "_season", "position"]):
        g = g.sort_values("week")
        for k in cutoffs:
            past, future = g[g["week"] <= k], g[g["week"] > k]
            if len(past) < MIN_GAMES_EACH_SIDE or len(future) < MIN_GAMES_EACH_SIDE:
                continue
            rows.append({**_features_through_k(past, pos, k),
                         "y": future.fppr.mean()})
    return pd.DataFrame(rows)


def _design_matrix(tr: pd.DataFrame) -> pd.DataFrame:
    return pd.get_dummies(tr[NUMERIC_FEATURES + ["pos"]], columns=["pos"])


def train_value_model(seasons=TRAIN_SEASONS, cutoffs=CUTOFFS,
                      random_state: int = 42) -> ValueReport:
    """Train + cross-validate the value model and rank feature importance."""
    tr = build_training_frame(seasons, cutoffs)
    X, y = _design_matrix(tr), tr["y"]
    cv = KFold(5, shuffle=True, random_state=random_state)
    model = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08,
                                          max_iter=300, min_samples_leaf=25,
                                          random_state=random_state)
    r2 = cross_val_score(model, X, y, cv=cv, scoring="r2")
    mae = -cross_val_score(model, X, y, cv=cv, scoring="neg_mean_absolute_error")
    model.fit(X, y)
    perm = permutation_importance(model, X, y, n_repeats=5,
                                  random_state=random_state, scoring="r2")
    imp = sorted(zip(X.columns, perm.importances_mean), key=lambda t: -t[1])
    from sklearn.metrics import r2_score
    return ValueReport(
        n_samples=len(tr), cv_r2_mean=float(r2.mean()), cv_r2_std=float(r2.std()),
        cv_mae=float(mae.mean()), baseline_r2=float(r2_score(y, tr["fppr_g"])),
        feature_importance=[(c, float(v)) for c, v in imp], model=model,
        feature_cols=list(X.columns))


def predict_values(report: ValueReport, season: int, as_of_week: int) -> pd.DataFrame:
    """Predicted rest-of-season value (fantasy pts/game) for a season's skill
    players, from their form through ``as_of_week``. Columns: player_id, player,
    position, team, games, value."""
    s = _weekly_skill((season,))
    rows: list[dict] = []
    for (pid, _season, pos), g in s.groupby(["player_id", "_season", "position"]):
        past = g.sort_values("week")
        past = past[past["week"] <= as_of_week]
        if len(past) < MIN_GAMES_EACH_SIDE:
            continue
        feat = _features_through_k(past, pos, as_of_week)
        last = past.iloc[-1]
        rows.append({"player_id": pid,
                     "player": last.get("player_display_name") or last.get("player_name"),
                     "position": pos, "team": last.get("team"),
                     "games": len(past), **feat})
    if not rows:
        return pd.DataFrame(columns=["player_id", "player", "position", "team",
                                     "games", "value"])
    pv = pd.DataFrame(rows)
    X = pd.get_dummies(pv[NUMERIC_FEATURES + ["pos"]], columns=["pos"])
    X = X.reindex(columns=report.feature_cols, fill_value=0)
    pv["value"] = report.model.predict(X).round(2)
    return (pv[["player_id", "player", "position", "team", "games", "value"]]
            .sort_values("value", ascending=False, ignore_index=True))
