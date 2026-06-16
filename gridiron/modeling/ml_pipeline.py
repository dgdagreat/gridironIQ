"""
Boardroom ML: predict Super Bowl probability from a team's positional cap profile.

A scikit-learn ``Pipeline`` (scale -> classifier) trained on the wide
``spending_features`` matrix, with:
  * stratified k-fold cross-validation (ROC-AUC), because the target is rare,
  * permutation feature importance, so the "which positions matter" story is
    model-agnostic and honest about correlated features.

Targets are intentionally swappable: ``sb_appearance`` (~6% positive) is the more
learnable signal; ``sb_win`` (~3%) is the headline but noisier.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from gridiron import db
from gridiron.ingestion.reference import POSITION_GROUP_ORDER

RELIABLE_START = 2011
FEATURE_COLS = [f"pct_{p}" for p in POSITION_GROUP_ORDER]


@dataclass
class ModelReport:
    """Result bundle from :func:`train_and_report`."""
    target: str
    model_name: str
    cv_auc_mean: float
    cv_auc_std: float
    n_samples: int
    n_positive: int
    importances: pd.DataFrame
    pipeline: Pipeline


def get_xy(target: str = "sb_appearance",
           min_season: int = RELIABLE_START) -> tuple[pd.DataFrame, pd.Series]:
    """Load the (X, y) matrices from ``v_team_season``."""
    df = db.query("SELECT * FROM v_team_season WHERE season >= :s", s=min_season)
    X = df[FEATURE_COLS].astype(float)
    y = df[target].astype(int)
    return X, y


def build_pipeline(model: str = "rf") -> Pipeline:
    """Return a scale->classifier pipeline. ``model`` in {"rf", "logreg"}."""
    if model == "logreg":
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    elif model == "rf":
        clf = RandomForestClassifier(
            n_estimators=400, max_depth=5, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
    else:  # pragma: no cover
        raise ValueError(f"unknown model '{model}'")
    return Pipeline([("scale", StandardScaler()), ("clf", clf)])


def cross_validate(pipeline: Pipeline, X: pd.DataFrame, y: pd.Series,
                   n_splits: int = 5) -> np.ndarray:
    """Stratified k-fold ROC-AUC scores (handles the rare positive class)."""
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    return cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc")


def train_and_report(target: str = "sb_appearance", model: str = "rf",
                     min_season: int = RELIABLE_START) -> ModelReport:
    """Cross-validate, fit on all data, and compute permutation importances."""
    X, y = get_xy(target, min_season)
    pipe = build_pipeline(model)
    auc = cross_validate(pipe, X, y)

    pipe.fit(X, y)
    perm = permutation_importance(pipe, X, y, scoring="roc_auc",
                                  n_repeats=20, random_state=42)
    importances = (
        pd.DataFrame({"feature": FEATURE_COLS,
                      "importance": perm.importances_mean,
                      "std": perm.importances_std})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )
    return ModelReport(
        target=target, model_name=model,
        cv_auc_mean=float(auc.mean()), cv_auc_std=float(auc.std()),
        n_samples=len(y), n_positive=int(y.sum()),
        importances=importances, pipeline=pipe,
    )


def predict_probability(report: ModelReport, features: dict[str, float]) -> float:
    """Score a single positional-spending profile -> SB probability."""
    row = pd.DataFrame([{c: float(features.get(c, 0.0)) for c in FEATURE_COLS}])
    return float(report.pipeline.predict_proba(row)[0, 1])


if __name__ == "__main__":  # quick smoke / demo
    pd.set_option("display.width", 160)
    for tgt in ("sb_appearance", "sb_win"):
        rep = train_and_report(target=tgt, model="rf")
        print(f"\n== target={rep.target}  model={rep.model_name} ==")
        print(f"   samples={rep.n_samples}  positives={rep.n_positive}")
        print(f"   CV ROC-AUC = {rep.cv_auc_mean:.3f} +/- {rep.cv_auc_std:.3f}")
        print("   top features by permutation importance:")
        print(rep.importances.head(6).to_string(index=False))
