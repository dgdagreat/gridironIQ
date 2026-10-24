"""
Defensive value: a learned, week-to-week forecast of a defender's production.

The companion to :mod:`player_value`, which covers offensive skill. Defenders
have no fantasy-PPR label, so the target here is an **IDP fantasy score** built
from the weekly box score (a balanced "big-play, tackle+1" format): tackles plus
bonuses for the disruption plays that separate difference-makers from
compilers — sacks, tackles for loss, QB hits, pass break-ups, forced fumbles,
takeaways and defensive scores. A gradient-boosted model then learns to forecast
a defender's **rest-of-season IDP/game** from his form so far, and confirms that
big plays — not just tackle volume — carry the signal.

    build_training_frame()  weekly stats, past seasons  -> (features, label) rows
    train_value_model()     fit + CV (R²/MAE) + permutation importance -> ValueReport
    predict_values()        current season through week k -> per-player value score

Scope: the five box-score defensive groups (IDL / EDGE / LB / CB / S). Offensive
line and specialists have no comparable box-score label and keep the hand-tuned
composite.
"""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, cross_val_score

from gridiron.ingestion.reference import classify_position
from gridiron.ingestion.rosters import load_weekly_stats
from gridiron.modeling.player_value import (
    CUTOFFS,
    MIN_GAMES_EACH_SIDE,
    TRAIN_SEASONS,
    ValueReport,
    _f,
    _new_model,
)

#: Defensive position groups with a box-score IDP label.
DEF_GROUPS = ("IDL", "EDGE", "LB", "CB", "S")
#: A sample needs this average IDP/game through the cutoff to count as a real
#: contributor (filters special-teamers who log the odd tackle).
MIN_IDP_PER_GAME = 2.0
#: Model features (per-game, cumulative through the cutoff week); ``grp`` one-hot.
NUMERIC_FEATURES = ["k", "gp", "tkl_g", "sack_g", "tfl_g", "qbh_g", "int_g",
                    "pd_g", "ff_g", "fr_g", "td_g", "idp_g"]


def _idp(df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-game IDP components and the IDP fantasy score to weekly rows."""
    solo = _f(df, "def_tackles_solo")
    asst = _f(df, "def_tackle_assists") + _f(df, "def_tackles_with_assist")
    df["tkl"] = solo + 0.5 * asst
    df["sack"] = _f(df, "def_sacks")
    df["tfl"] = _f(df, "def_tackles_for_loss")
    df["qbh"] = _f(df, "def_qb_hits")
    df["intc"] = _f(df, "def_interceptions")
    df["pd"] = _f(df, "def_pass_defended")
    df["ff"] = _f(df, "def_fumbles_forced")
    df["fr"] = _f(df, "fumble_recovery_own") + _f(df, "fumble_recovery_opp")
    df["dtd"] = _f(df, "def_tds")
    df["saf"] = _f(df, "def_safeties")
    # big-play, tackle+1 IDP: tackle 1 / assist 0.5 / sack 2 / TFL 1 / QB hit 1 /
    # INT 3 / PD 1.5 / forced fumble 2 / recovery 2 / def TD 6 / safety 2.
    df["idp"] = (df.tkl + 2 * df.sack + df.tfl + df.qbh + 3 * df.intc
                 + 1.5 * df.pd + 2 * df.ff + 2 * df.fr + 6 * df.dtd + 2 * df.saf)
    return df


def _weekly_def(seasons) -> pd.DataFrame:
    """Regular-season weekly rows for box-score defenders, with IDP components."""
    frames = []
    for yr in seasons:
        w = load_weekly_stats(yr)
        w = w[w.get("season_type", pd.Series("REG", index=w.index)).eq("REG")].copy()
        w["grp"] = w["position"].map(classify_position)
        w = w[w["grp"].isin(DEF_GROUPS)].copy()
        w["_season"] = yr
        frames.append(w)
    return _idp(pd.concat(frames, ignore_index=True))


def _features_through_k(past: pd.DataFrame, grp: str, k: int) -> dict:
    gp = len(past)
    return dict(grp=grp, k=k, gp=gp,
                tkl_g=past.tkl.sum() / gp, sack_g=past.sack.sum() / gp,
                tfl_g=past.tfl.sum() / gp, qbh_g=past.qbh.sum() / gp,
                int_g=past.intc.sum() / gp, pd_g=past.pd.sum() / gp,
                ff_g=past.ff.sum() / gp, fr_g=past.fr.sum() / gp,
                td_g=past.dtd.sum() / gp, idp_g=past.idp.sum() / gp)


def build_training_frame(seasons=TRAIN_SEASONS, cutoffs=CUTOFFS) -> pd.DataFrame:
    """One row per (player, season, cutoff): features through week k + the label
    ``y`` = mean IDP points/game over the rest of that season."""
    s = _weekly_def(seasons)
    rows: list[dict] = []
    for (_pid, _season, grp), g in s.groupby(["player_id", "_season", "grp"]):
        g = g.sort_values("week")
        for k in cutoffs:
            past, future = g[g["week"] <= k], g[g["week"] > k]
            if len(past) < MIN_GAMES_EACH_SIDE or len(future) < MIN_GAMES_EACH_SIDE:
                continue
            if past.idp.sum() / len(past) < MIN_IDP_PER_GAME:
                continue
            rows.append({**_features_through_k(past, grp, k), "y": future.idp.mean()})
    return pd.DataFrame(rows)


def _design_matrix(tr: pd.DataFrame) -> pd.DataFrame:
    return pd.get_dummies(tr[NUMERIC_FEATURES + ["grp"]], columns=["grp"])


def fit_model(seasons=TRAIN_SEASONS, cutoffs=CUTOFFS, random_state: int = 42):
    """Fit the defense value model (no CV) -> ``(model, feature_cols)``."""
    tr = build_training_frame(seasons, cutoffs)
    X, y = _design_matrix(tr), tr["y"]
    model = _new_model(random_state).fit(X, y)
    return model, list(X.columns)


def train_value_model(seasons=TRAIN_SEASONS, cutoffs=CUTOFFS,
                      random_state: int = 42) -> ValueReport:
    """Train + cross-validate the defense value model and rank feature importance."""
    from sklearn.metrics import r2_score
    tr = build_training_frame(seasons, cutoffs)
    X, y = _design_matrix(tr), tr["y"]
    cv = KFold(5, shuffle=True, random_state=random_state)
    model = _new_model(random_state)
    r2 = cross_val_score(model, X, y, cv=cv, scoring="r2")
    mae = -cross_val_score(model, X, y, cv=cv, scoring="neg_mean_absolute_error")
    model.fit(X, y)
    perm = permutation_importance(model, X, y, n_repeats=5,
                                  random_state=random_state, scoring="r2")
    imp = sorted(zip(X.columns, perm.importances_mean), key=lambda t: -t[1])
    return ValueReport(
        n_samples=len(tr), cv_r2_mean=float(r2.mean()), cv_r2_std=float(r2.std()),
        cv_mae=float(mae.mean()), baseline_r2=float(r2_score(y, tr["idp_g"])),
        feature_importance=[(c, float(v)) for c, v in imp], model=model,
        feature_cols=list(X.columns))


def season_values(season: int, as_of_week: int | None = None,
                  train_seasons=TRAIN_SEASONS) -> pd.Series:
    """``gsis_id -> projected IDP/game`` for a season's box-score defenders.
    Trains on seasons strictly before ``season`` (no leakage) and predicts through
    the latest played week unless ``as_of_week`` is given. Empty on any failure."""
    try:
        seasons = tuple(s for s in train_seasons if s < season) or train_seasons
        model, cols = fit_model(seasons)
        if as_of_week is None:
            w = load_weekly_stats(season)
            reg = w[w.get("season_type", pd.Series("REG", index=w.index)).eq("REG")]
            as_of_week = int(reg["week"].max())
        vals = predict_values(model, cols, season, as_of_week)
    except Exception:  # noqa: BLE001 - value is an enhancement; never break the refresh
        return pd.Series(dtype="float64", name="ml_value")
    return vals.set_index("player_id")["value"].rename("ml_value")


def predict_values(model, feature_cols, season: int, as_of_week: int) -> pd.DataFrame:
    """Predicted rest-of-season IDP/game for a season's defenders, from their form
    through ``as_of_week``. Columns: player_id, player, position, team, games, value."""
    s = _weekly_def((season,))
    rows: list[dict] = []
    for (pid, _season, grp), g in s.groupby(["player_id", "_season", "grp"]):
        past = g.sort_values("week")
        past = past[past["week"] <= as_of_week]
        if len(past) < MIN_GAMES_EACH_SIDE:
            continue
        if past.idp.sum() / len(past) < MIN_IDP_PER_GAME:
            continue
        last = past.iloc[-1]
        rows.append({"player_id": pid,
                     "player": last.get("player_display_name") or last.get("player_name"),
                     "position": grp, "team": last.get("team"),
                     "games": len(past), **_features_through_k(past, grp, as_of_week)})
    if not rows:
        return pd.DataFrame(columns=["player_id", "player", "position", "team",
                                     "games", "value"])
    pv = pd.DataFrame(rows)
    X = pd.get_dummies(pv[NUMERIC_FEATURES + ["grp"]], columns=["grp"])
    X = X.reindex(columns=feature_cols, fill_value=0)
    pv["value"] = model.predict(X).round(2)
    return (pv[["player_id", "player", "position", "team", "games", "value"]]
            .sort_values("value", ascending=False, ignore_index=True))
