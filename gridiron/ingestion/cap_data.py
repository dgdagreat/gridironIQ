"""
Cap data ingestion: nflverse / OverTheCap contracts -> positional spending shares.

Pipeline stages (each a pure, testable function returning a DataFrame):

    download_contracts()        raw historical_contracts asset  -> data/raw/*.parquet
    load_raw_contracts()        cached file                     -> contracts DataFrame
    build_player_year_caps()    explode nested per-year detail  -> one row / player / season
    build_positional_spending() aggregate                       -> team x season x position-group
    build_spending_features()   pivot                           -> one row / team-season (model-ready)

The key modeling unit is **share of the salary cap**, not raw dollars: a position's
cap_number for a team-season divided by that season's league cap. We take that share
directly from each contract-year's ``cap_percent`` (self-consistent with the source)
and cross-check it against dollars / the league-cap reference table.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from gridiron import config
from gridiron.ingestion.reference import (
    POSITION_GROUP_ORDER,
    canonical_team,
    classify_position,
)

log = logging.getLogger(__name__)

_RAW_PARQUET = config.RAW_DIR / "historical_contracts.parquet"
_RAW_CSV = config.RAW_DIR / "historical_contracts.csv.gz"


# --------------------------------------------------------------------------- #
# Stage 1 -- download (cached)
# --------------------------------------------------------------------------- #
def download_contracts(force: bool = False, timeout: int = 60) -> Path:
    """Download the historical_contracts asset to ``data/raw`` (cached).

    Tries the parquet asset first, falling back to the gzipped CSV. Returns the
    local path that was populated.
    """
    if _RAW_PARQUET.exists() and not force:
        log.info("Using cached contracts parquet: %s", _RAW_PARQUET)
        return _RAW_PARQUET

    for url, dest in (
        (config.CONTRACTS_PARQUET_URL, _RAW_PARQUET),
        (config.CONTRACTS_CSV_URL, _RAW_CSV),
    ):
        try:
            log.info("Downloading %s", url)
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            log.info("Saved %.1f MB -> %s", len(resp.content) / 1e6, dest)
            return dest
        except requests.RequestException as exc:  # pragma: no cover - network
            log.warning("Failed to fetch %s (%s); trying next source", url, exc)

    raise RuntimeError(
        "Could not download contracts data from any nflverse source. "
        "Check connectivity or download historical_contracts.parquet manually "
        f"into {config.RAW_DIR}."
    )


def load_raw_contracts(force_download: bool = False) -> pd.DataFrame:
    """Return the raw contracts table, downloading on first use."""
    path = download_contracts(force=force_download)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, compression="gzip", low_memory=False)


# --------------------------------------------------------------------------- #
# Stage 2 -- explode the nested per-year cap detail
# --------------------------------------------------------------------------- #
#: Candidate names for the nested per-season breakdown across source versions.
_NESTED_COLS = ("cols", "year_details", "season_details")


def build_player_year_caps(contracts: pd.DataFrame) -> pd.DataFrame:
    """Explode each contract's per-year cap detail into tidy per-season rows.

    Output columns: ``otc_id, player, position, season, team, cap_number,
    cap_percent``. Each row is one player's cap charge for one season, attributed
    to the team carried *inside* that season's record (so mid-contract trades land
    on the right team).

    Falls back to a coarse ``apy_cap_pct`` @ ``year_signed`` approximation when no
    nested per-year detail is present in the source.
    """
    nested_col = next((c for c in _NESTED_COLS if c in contracts.columns), None)

    if nested_col is None:
        log.warning("No nested per-year column found; using apy_cap_pct fallback")
        return _fallback_from_apy(contracts)

    records: list[dict[str, object]] = []
    for row in contracts.itertuples(index=False):
        nested = getattr(row, nested_col, None)
        if nested is None:
            continue
        try:
            items = list(nested)
        except TypeError:
            continue
        base = {
            "otc_id": getattr(row, "otc_id", None),
            "player": getattr(row, "player", None),
            "position": getattr(row, "position", None),
            "year_signed": getattr(row, "year_signed", None),
        }
        for item in items:
            rec = _coerce_record(item)
            if rec is None:
                continue
            records.append({**base, **rec})

    if not records:
        log.warning("Nested column '%s' held no rows; using apy fallback", nested_col)
        return _fallback_from_apy(contracts)

    exploded = pd.DataFrame.from_records(records)
    return _normalize_player_year(exploded)


def _coerce_record(item: object) -> dict | None:
    """Best-effort convert one nested element into a plain dict."""
    if isinstance(item, dict):
        return dict(item)
    # pyarrow/pandas can hand back Series, namedtuples, or struct-likes
    for converter in (lambda x: x.to_dict(), dict):
        try:
            return converter(item)  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001 - intentionally permissive
            continue
    return None


def _normalize_player_year(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names/dtypes coming out of the nested explode."""
    rename = {
        "year": "season",
        "cap_number": "cap_number",
        "cap_percent": "cap_percent",
        "cap_pct": "cap_percent",
        "team": "team",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "season" not in df.columns:
        raise KeyError("nested cap detail is missing a 'year'/'season' field")

    df["season"] = pd.to_numeric(df["season"], errors="coerce")
    if "team" not in df.columns:
        df["team"] = None
    df["team"] = df["team"].map(canonical_team)
    for col in ("cap_number", "cap_percent"):
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["cap_number"] = _millions_to_dollars(df["cap_number"])
    df["cap_percent"] = _to_fraction(df["cap_percent"])
    df["year_signed"] = pd.to_numeric(df.get("year_signed"), errors="coerce")

    df = df.dropna(subset=["season"])
    # Drop sentinel/garbage years (the source carries year_signed==0 rows, etc.)
    df = df[df["season"].between(1990, 2035)]
    df["season"] = df["season"].astype(int)

    df = _select_governing_contract(df)

    keep = ["otc_id", "player", "position", "season", "team",
            "cap_number", "cap_percent", "year_signed"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def _select_governing_contract(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse overlapping contracts to one cap charge per player-season.

    ``historical_contracts`` stores every deal a player ever signed, and each
    projects a full multi-year cap schedule -- so an extension and the deal it
    replaced both carry the transition seasons. The contract actually governing a
    season is the most recently signed one that was already in effect (
    ``year_signed <= season``). Summing without this de-dup double-counts cap.
    """
    df = df[df["year_signed"].notna() & (df["year_signed"] <= df["season"])]
    df = df.sort_values(["otc_id", "season", "year_signed", "cap_number"])
    return df.drop_duplicates(subset=["otc_id", "season"], keep="last")


def _fallback_from_apy(contracts: pd.DataFrame) -> pd.DataFrame:
    """Coarse per-season proxy when only signing-level fields are available."""
    cols = {
        "otc_id": "otc_id", "player": "player", "position": "position",
        "team": "team", "year_signed": "season", "apy": "cap_number",
        "apy_cap_pct": "cap_percent",
    }
    have = {k: v for k, v in cols.items() if k in contracts.columns}
    df = contracts[list(have)].rename(columns=have).copy()
    df["season"] = pd.to_numeric(df.get("season"), errors="coerce")
    df["team"] = df.get("team").map(canonical_team)
    for col in ("cap_number", "cap_percent"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["cap_percent"] = _to_fraction(df["cap_percent"])
    return df.dropna(subset=["season"]).assign(season=lambda d: d["season"].astype(int))


def _to_fraction(s: pd.Series) -> pd.Series:
    """Normalize a cap-percentage column to a 0..1 fraction.

    Sources variously store this as a fraction (0.08) or a percentage (8.0).
    Detect via the median of positive values and rescale once.
    """
    positive = s[s > 0]
    if not positive.empty and positive.median() > 1.0:
        return s / 100.0
    return s


def _millions_to_dollars(s: pd.Series) -> pd.Series:
    """Scale cap figures to whole dollars.

    The nflverse nested cap detail stores cap numbers in millions (6.58 ->
    $6.58M). Detect the unit from the magnitude of positive values and rescale.
    """
    positive = s[s > 0]
    if not positive.empty and positive.median() < 1_000:
        return s * 1_000_000
    return s


# --------------------------------------------------------------------------- #
# Stage 3 -- aggregate to team x season x position group
# --------------------------------------------------------------------------- #
def build_positional_spending(player_year_caps: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-player-season caps into positional spending shares.

    Output columns: ``season, team, era, pos_group, cap_dollars, cap_pct,
    cap_pct_ref, n_players``. ``cap_pct`` is the sum of source cap shares;
    ``cap_pct_ref`` is dollars / league cap (a cross-check).
    """
    df = player_year_caps.copy()
    df["pos_group"] = df["position"].map(classify_position)
    # Clamp to the labeled analysis window: >= cap era start, <= last season with
    # a known Super Bowl outcome. Projected future out-years would otherwise enter
    # as incomplete rosters with no target label.
    df = df[df["season"].between(config.START_SEASON, config.END_SEASON)]
    df = df[df["team"].notna()]

    agg = (
        df.groupby(["season", "team", "pos_group"], dropna=False)
        .agg(
            cap_dollars=("cap_number", "sum"),
            cap_pct=("cap_percent", "sum"),
            n_players=("otc_id", "nunique"),
        )
        .reset_index()
    )

    # Within-team-season normalized share: each position as a fraction of the
    # team's *accounted* cap. Controls for the source's lower historical coverage
    # so distributions stay comparable across eras.
    team_total = agg.groupby(["season", "team"])["cap_pct"].transform("sum")
    agg["cap_pct_norm"] = (agg["cap_pct"] / team_total).where(team_total > 0)

    # Cross-check share from dollars / league cap reference table.
    agg["league_cap"] = agg["season"].map(config.LEAGUE_SALARY_CAP)
    agg["cap_pct_ref"] = agg["cap_dollars"] / agg["league_cap"]
    agg["era"] = agg["season"].map(config.era_for_season)

    cols = ["season", "team", "era", "pos_group", "cap_dollars",
            "cap_pct", "cap_pct_norm", "cap_pct_ref", "n_players"]
    return agg[cols].sort_values(["season", "team", "pos_group"], ignore_index=True)


# --------------------------------------------------------------------------- #
# Stage 4 -- pivot to a model-ready wide table (one row per team-season)
# --------------------------------------------------------------------------- #
def build_spending_features(positional_spending: pd.DataFrame) -> pd.DataFrame:
    """Pivot positional shares wide: one row per team-season, a column per group.

    Columns are fixed and deterministic: ``season, team, era`` then one
    ``pct_<GROUP>`` per entry in :data:`POSITION_GROUP_ORDER` (missing groups
    filled with 0.0), then ``total_pct``. Unmapped positions (``UNK``) are
    excluded from features. This is the matrix the Boardroom ML pipeline consumes.
    """
    known = positional_spending[positional_spending["pos_group"].isin(POSITION_GROUP_ORDER)]
    wide = (
        known.pivot_table(
            index=["season", "team", "era"],
            columns="pos_group",
            values="cap_pct",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    wide.columns.name = None

    # Guarantee every standard position column exists, in canonical order.
    for group in POSITION_GROUP_ORDER:
        if group not in wide.columns:
            wide[group] = 0.0
    wide = wide.rename(columns={g: f"pct_{g}" for g in POSITION_GROUP_ORDER})

    pct_cols = [f"pct_{g}" for g in POSITION_GROUP_ORDER]
    wide["total_pct"] = wide[pct_cols].sum(axis=1)
    return wide[["season", "team", "era", *pct_cols, "total_pct"]]
