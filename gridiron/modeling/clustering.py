"""
Boardroom clustering: discover "roster archetypes" from cap-spending profiles.

K-means over the standardized positional-share matrix groups team-seasons into
spending archetypes (e.g. "QB-and-trenches", "secondary-heavy", "balanced").
Each archetype is then scored by how often it reaches / wins the Super Bowl --
turning the clusters into a story about *which build wins*.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from gridiron import db
from gridiron.ingestion.reference import POSITION_GROUP_ORDER

RELIABLE_START = 2011
FEATURE_COLS = [f"pct_{p}" for p in POSITION_GROUP_ORDER]


@dataclass
class ClusterResult:
    """Result bundle from :func:`cluster_archetypes`."""
    assignments: pd.DataFrame      # season, team, archetype, + features
    profiles: pd.DataFrame         # mean share per position, per archetype
    success: pd.DataFrame          # SB appearance/win rate per archetype
    model: KMeans
    scaler: StandardScaler


def cluster_archetypes(k: int = 5,
                       min_season: int = RELIABLE_START) -> ClusterResult:
    """Cluster team-seasons into ``k`` spending archetypes and score each."""
    df = db.query("SELECT * FROM v_team_season WHERE season >= :s", s=min_season)
    X = df[FEATURE_COLS].astype(float)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = KMeans(n_clusters=k, n_init=10, random_state=42)
    df = df.assign(archetype=model.fit_predict(Xs))

    profiles = (
        df.groupby("archetype")[FEATURE_COLS].mean()
        .rename(columns=lambda c: c.replace("pct_", ""))
        .round(3)
    )
    success = (
        df.groupby("archetype")
        .agg(n_team_seasons=("team", "size"),
             sb_appearance_rate=("sb_appearance", "mean"),
             sb_win_rate=("sb_win", "mean"))
        .round(3)
    )
    profiles["label"] = _archetype_labels(model, scaler)

    keep = ["season", "team", "era", "archetype", *FEATURE_COLS,
            "sb_appearance", "sb_win"]
    return ClusterResult(
        assignments=df[keep], profiles=profiles, success=success,
        model=model, scaler=scaler,
    )


def _archetype_labels(model: KMeans, scaler: StandardScaler) -> pd.Series:
    """Name each archetype by its most *distinctive* investments.

    Uses the standardized cluster centroid (z-scores), so labels reflect where a
    cluster spends *above league average* -- not OL, which is the largest raw
    share for nearly every team and would otherwise dominate every label.
    """
    positions = [c.replace("pct_", "") for c in FEATURE_COLS]
    centers = pd.DataFrame(model.cluster_centers_, columns=positions)
    labels = {
        i: " + ".join(centers.loc[i].sort_values(ascending=False).head(2).index)
        for i in centers.index
    }
    return pd.Series(labels, name="label")


if __name__ == "__main__":  # quick smoke / demo
    pd.set_option("display.width", 180)
    res = cluster_archetypes(k=5)
    print("Archetype success rates:")
    print(res.success.join(res.profiles["label"]).to_string())
    print("\nArchetype spending profiles (mean share):")
    print(res.profiles.to_string())
