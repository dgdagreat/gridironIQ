"""
MVP / award "buzz" — a market-implied reputation signal, live from Kalshi.

Prediction-market prices *are* implied probabilities (a 28¢ "Josh Allen MVP"
contract = 28%), so they're a cleaner, vig-free read on the media/expert sentiment
that "MVP talk" means than sportsbook odds — and Kalshi exposes them keyless.

We pull the three individual-award markets (MVP / OPOY / DPOY) and use each
candidate's price as his buzz. Matching is by (name, side-of-ball) so same-named
players don't cross-contaminate — the QB Josh Allen picks up MVP buzz, the edge
Josh Allen would only pick up *defensive* buzz. If the live fetch fails (network /
API change), we fall back to the hand-entered :data:`AWARD_BUZZ` snapshot so a
refresh never breaks. The signal is applied with a small weight downstream (see
``roster_strength.BUZZ_WEIGHT``): it informs the ranking, never overturns it.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import requests

log = logging.getLogger(__name__)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
#: (Kalshi series ticker, award, side of the ball). Any award Kalshi isn't
#: trading yet (DPOY/OPOY often open later) falls back to the manual snapshot.
AWARD_SERIES: list[tuple[str, str, str]] = [
    ("KXNFLMVP", "MVP", "off"),    # AP Regular-Season MVP (usually a QB)
    ("KXNFLOPOY", "OPOY", "off"),  # Offensive Player of the Year
    ("KXNFLDPOY", "DPOY", "def"),  # Defensive Player of the Year
]

#: Position groups on each side of the ball (for name/side matching).
_OFF_POS = {"QB", "RB", "WR", "TE", "OL"}
_DEF_POS = {"IDL", "EDGE", "LB", "CB", "S"}
#: Ignore award longshots below this implied probability — a 1% MVP contract
#: isn't "buzz," and a live market lists dozens of them.
MIN_BUZZ = 0.02

# --------------------------------------------------------------------------- #
# Manual fallback snapshot — only used if the live Kalshi fetch fails.
# (player, team, award, implied_win_prob); re-pull with a refresh when it drifts.
# --------------------------------------------------------------------------- #
AS_OF = "2026-10-22"  # Week 7, 2026 — fallback snapshot date
AWARD_BUZZ: list[tuple[str, str, str, float]] = [
    ("Josh Allen",         "BUF", "MVP",  0.31),
    ("Brock Purdy",        "SF",  "MVP",  0.27),
    ("Patrick Mahomes",    "KC",  "MVP",  0.10),
    ("Joe Burrow",         "CIN", "MVP",  0.085),
    ("Drake Maye",         "NE",  "MVP",  0.083),
    ("Kenneth Walker III", "KC",  "OPOY", 0.33),
    ("Jahmyr Gibbs",       "DET", "OPOY", 0.29),
    ("Will Anderson Jr.",  "HOU", "DPOY", 0.38),
    ("Fred Warner",        "SF",  "DPOY", 0.11),
    ("Dallas Turner",      "MIN", "DPOY", 0.09),
    ("Greg Rousseau",      "BUF", "DPOY", 0.08),
    ("Aidan Hutchinson",   "DET", "DPOY", 0.063),
]

_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$")


def _norm(name: object) -> str:
    """Lowercase, drop periods and a trailing Jr./III/etc. so names match cleanly."""
    s = str(name).lower().replace(".", "").strip()
    return _SUFFIX.sub("", s).strip()


def _side(pos_group: object) -> str | None:
    pg = str(pos_group).upper()
    return "off" if pg in _OFF_POS else "def" if pg in _DEF_POS else None


def _market_price(m: dict) -> float:
    """Implied probability (0–1) for a Kalshi market, across field-name variants."""
    for key in ("last_price_dollars", "yes_bid_dollars", "yes_ask_dollars"):
        v = m.get(key)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    # Older integer-cent fields, just in case.
    for key in ("last_price", "yes_bid", "yes_ask"):
        v = m.get(key)
        if v:
            return float(v) / 100.0
    return 0.0


def _fetch_event_markets(series: str, timeout: int) -> list[dict]:
    """The open event's candidate markets for a Kalshi series ([] if none)."""
    for params in ({"series_ticker": series, "limit": 1, "status": "open"},
                   {"series_ticker": series, "limit": 1}):
        ev = requests.get(f"{KALSHI_BASE}/events", params=params, timeout=timeout)
        ev.raise_for_status()
        events = ev.json().get("events") or []
        if events:
            mk = requests.get(f"{KALSHI_BASE}/markets",
                              params={"event_ticker": events[0]["event_ticker"],
                                      "limit": 200}, timeout=timeout)
            mk.raise_for_status()
            return mk.json().get("markets") or []
    return []


@lru_cache(maxsize=1)
def fetch_live_buzz(timeout: int = 15) -> tuple[tuple[str, tuple], ...]:
    """Live award odds from Kalshi, per award → ``((award, ((name, side, prob),…)),…)``.

    Only awards that are actually trading come back; the caller fills the rest
    from the manual snapshot. Cached per process so one refresh hits the API once.
    """
    out: list[tuple[str, tuple]] = []
    for series, award, side in AWARD_SERIES:
        try:
            entries = tuple((_norm(m["yes_sub_title"]), side, _market_price(m))
                            for m in _fetch_event_markets(series, timeout)
                            if m.get("yes_sub_title") and _market_price(m) > 0)
        except (requests.RequestException, ValueError, KeyError) as exc:
            log.warning("Kalshi buzz fetch failed for %s: %s", series, exc)
            entries = ()
        if entries:
            out.append((award, entries))
    log.info("Live award buzz from Kalshi: %s",
             {a: len(e) for a, e in out} or "none (using snapshot)")
    return tuple(out)


def _manual_by_award() -> dict[str, list[tuple[str, str, float]]]:
    out: dict[str, list[tuple[str, str, float]]] = {}
    for player, _team, award, prob in AWARD_BUZZ:
        side = "def" if award == "DPOY" else "off"
        out.setdefault(award, []).append((_norm(player), side, prob))
    return out


def _buzz_index() -> dict[tuple[str, str], float]:
    """{(normalized_name, side) -> buzz 0..1}. Per award: live Kalshi if it's
    trading, else the manual snapshot; a player keeps his best award buzz."""
    live = dict(fetch_live_buzz())
    manual = _manual_by_award()
    idx: dict[tuple[str, str], float] = {}
    for award in ("MVP", "OPOY", "DPOY"):
        for nm, side, p in live.get(award) or manual.get(award, []):
            key = (nm, side)
            idx[key] = max(idx.get(key, 0.0), float(p))
    return idx


def player_buzz(names, pos_groups) -> list[float]:
    """Award buzz (0.0 where none) for aligned player names + position groups.

    Matched by (name, side-of-ball): an offensive player only picks up MVP/OPOY
    buzz, a defender only DPOY — so the two Josh Allens never collide.
    """
    idx = _buzz_index()
    out: list[float] = []
    for n, pg in zip(names, pos_groups):
        s = _side(pg)
        v = idx.get((_norm(n), s), 0.0) if s else 0.0
        out.append(v if v >= MIN_BUZZ else 0.0)
    return out
