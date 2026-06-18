"""
ESPN live-roster cross-check — automatic staleness detection.

Our roster of record is nflverse (see ``rosters.py``). ESPN's public team-roster
API reflects transactions within ~a day, so comparing the two per team flags any
drift the instant our source lags: players ESPN has that we're missing (a signing
we haven't picked up) or players we still list that ESPN has dropped.

Matching is by nflverse ``gsis_id`` (robust to name spelling — "Chris" vs
"Christian"), with a normalized-name fallback for players ESPN lists without a
gsis mapping (recent rookies). Nothing here feeds the Maxer's talent scores; it's
purely an audit/alarm.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time

import pandas as pd
import requests

from gridiron import config
from gridiron.ingestion.reference import CANONICAL_TEAMS, canonical_team

log = logging.getLogger(__name__)

ESPN_ROSTER_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
                   "teams/{abbr}/roster")
PLAYERS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
               "players/players.parquet")

#: ESPN abbreviations match ours except Washington (WSH vs WAS).
ESPN_ABBR: dict[str, str] = {t: ("WSH" if t == "WAS" else t) for t in CANONICAL_TEAMS}

#: A team needs review if this many players differ in either direction (small
#: diffs are normal source-timing / practice-squad churn).
DRIFT_THRESHOLD = 6


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm(name) -> str:
    """Normalize a full name for fallback matching (lowercased, alpha-only)."""
    if not isinstance(name, str):
        return ""
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name.lower())
    return re.sub(r"[^a-z]", "", s)


def _fnln(name) -> str:
    """First-initial + last name key — bridges nickname variants (Gabe/Gabriel)."""
    if not isinstance(name, str):
        return ""
    parts = [p for p in re.sub(r"[^a-z ]", "", name.lower()).split() if p not in _SUFFIXES]
    if len(parts) >= 2:
        return parts[0][0] + parts[-1]
    return parts[0] if parts else ""


def load_espn_roster(timeout: int = 30) -> pd.DataFrame:
    """Pull all 32 teams' current rosters from ESPN -> (team, espn_id, player, position)."""
    rows: list[dict] = []
    for canon, abbr in ESPN_ABBR.items():
        try:
            data = requests.get(ESPN_ROSTER_URL.format(abbr=abbr), timeout=timeout).json()
        except requests.RequestException as exc:  # pragma: no cover - network
            log.warning("ESPN roster fetch failed for %s: %s", canon, exc)
            continue
        for group in data.get("athletes", []):
            for p in group.get("items", []):
                rows.append({
                    "team": canon,
                    "espn_id": str(p.get("id")),
                    "player": p.get("fullName"),
                    "position": (p.get("position") or {}).get("abbreviation"),
                })
    return pd.DataFrame(rows)


def espn_to_gsis(*, ttl_hours: float = 24, force: bool = False) -> dict[str, str]:
    """Map ESPN athlete id -> nflverse gsis_id from the players table (cached)."""
    dest = config.RAW_DIR / "players.parquet"
    stale = not dest.exists() or (time.time() - dest.stat().st_mtime) / 3600 >= ttl_hours
    if stale or force:
        resp = requests.get(PLAYERS_URL, timeout=90)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    pl = pd.read_parquet(dest, columns=["espn_id", "gsis_id"]).dropna()
    pl["espn_id"] = pd.to_numeric(pl["espn_id"], errors="coerce").dropna().astype("int64").astype(str)
    return dict(zip(pl["espn_id"], pl["gsis_id"]))


def crosscheck_rosters(*, force: bool = False) -> pd.DataFrame:
    """Compare our nflverse roster to ESPN's live roster, per team.

    Returns one row per team: counts, the differing player names in each
    direction, and a ``flagged`` marker when drift exceeds the threshold.
    """
    from gridiron.ingestion import rosters  # local import avoids a cycle

    _, ours = rosters.load_current_roster(force=force)
    ours = ours[ours["status"].eq("ACT")] if "status" in ours else ours
    ours = ours.assign(team=ours["team"].map(canonical_team),
                       nname=ours["full_name"].map(_norm),
                       fnln=ours["full_name"].map(_fnln))

    espn = load_espn_roster()
    id_map = espn_to_gsis(force=force)
    espn = espn.assign(gsis_id=espn["espn_id"].map(id_map),
                       nname=espn["player"].map(_norm),
                       fnln=espn["player"].map(_fnln))

    rows: list[dict] = []
    for team in sorted(CANONICAL_TEAMS):
        o, e = ours[ours["team"] == team], espn[espn["team"] == team]
        o_ids, o_names, o_fnln = set(o["gsis_id"].dropna()), set(o["nname"]), set(o["fnln"])
        e_ids, e_names, e_fnln = set(e["gsis_id"].dropna()), set(e["nname"]), set(e["fnln"])

        only_espn = e[~e["gsis_id"].isin(o_ids) & ~e["nname"].isin(o_names) & ~e["fnln"].isin(o_fnln)]
        only_ours = o[~o["gsis_id"].isin(e_ids) & ~o["nname"].isin(e_names) & ~o["fnln"].isin(e_fnln)]
        rows.append({
            "team": team,
            "n_ours": len(o),
            "n_espn": len(e),
            "missing_from_ours": "; ".join(sorted(only_espn["player"].dropna())),
            "dropped_per_espn": "; ".join(sorted(only_ours["full_name"].dropna())),
            "n_missing_from_ours": len(only_espn),
            "n_dropped_per_espn": len(only_ours),
        })

    df = pd.DataFrame(rows)
    df["flagged"] = ((df["n_missing_from_ours"] >= DRIFT_THRESHOLD) |
                     (df["n_dropped_per_espn"] >= DRIFT_THRESHOLD)).astype(int)
    df["checked_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return df.sort_values(["flagged", "n_missing_from_ours"], ascending=False,
                          ignore_index=True)
