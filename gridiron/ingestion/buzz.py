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

# --------------------------------------------------------------------------- #
# Recognition: recent All-Pro selections (the "voting buzz" / Pro-Bowl-type
# accolade signal). Scraped from Wikipedia's All-Pro Team pages, verified by
# hand, and baked here so it's reliable (re-scrape + review once a year when the
# teams are announced). A player recognized by the voters as elite gets a small
# recognition boost on top of the data-driven grade — so proven stars grade out.
# --------------------------------------------------------------------------- #
ACCOLADES_AS_OF = "2026-10-23"  # through the 2025 All-Pro teams
#: How much each season's selection counts (recency-decayed).
ALL_PRO_RECENCY: dict[int, float] = {2025: 1.0, 2024: 0.6}
#: season -> side -> [players selected All-Pro (1st or 2nd team)].
ALL_PRO: dict[int, dict[str, list[str]]] = {
    2025: {
        "off": ["Matthew Stafford", "Drake Maye", "Bijan Robinson", "James Cook",
                "Christian McCaffrey", "Jonathan Taylor", "Kyle Juszczyk",
                "Patrick Ricard", "Puka Nacua", "Jaxon Smith-Njigba",
                "Ja'Marr Chase", "George Pickens", "Chris Olave",
                "Amon-Ra St. Brown", "Trey McBride", "Kyle Pitts", "Garett Bolles",
                "Trent Williams", "Joe Thuney", "Quenton Nelson", "Creed Humphrey",
                "Aaron Brewer", "Quinn Meinerz", "Chris Lindstrom", "Penei Sewell",
                "Darnell Wright"],
        "def": ["Myles Garrett", "Micah Parsons", "Will Anderson Jr.",
                "Aidan Hutchinson", "Danielle Hunter", "Brian Burns",
                "Jeffery Simmons", "Zach Allen", "Leonard Williams",
                "Quinnen Williams", "Cameron Heyward", "Jordyn Brooks",
                "Jack Campbell", "Ernest Jones", "Devin Lloyd", "Nik Bonitto",
                "Derek Stingley Jr.", "Quinyon Mitchell", "Patrick Surtain II",
                "Jaycee Horn", "Devon Witherspoon", "Cooper DeJean",
                "Derwin James", "Kyle Hamilton", "Kevin Byard", "Jessie Bates",
                "Talanoa Hufanga", "Xavier McKinney"],
    },
    2024: {
        "off": ["Lamar Jackson", "Josh Allen", "Saquon Barkley", "Derrick Henry",
                "Patrick Ricard", "Kyle Juszczyk", "Ja'Marr Chase",
                "Justin Jefferson", "Amon-Ra St. Brown", "Terry McLaurin",
                "CeeDee Lamb", "A.J. Brown", "Brock Bowers", "George Kittle",
                "Tristan Wirfs", "Jordan Mailata", "Joe Thuney", "Quenton Nelson",
                "Creed Humphrey", "Frank Ragnow", "Quinn Meinerz",
                "Chris Lindstrom", "Penei Sewell", "Lane Johnson",
                "Landon Dickerson"],
        "def": ["Myles Garrett", "Trey Hendrickson", "T.J. Watt", "Nik Bonitto",
                "Andrew Van Ginkel", "Cameron Heyward", "Chris Jones",
                "Dexter Lawrence", "Zach Allen", "Jalen Carter", "Zack Baun",
                "Fred Warner", "Roquan Smith", "Frankie Luvu", "Bobby Wagner",
                "Zaire Franklin", "Patrick Surtain II", "Derek Stingley Jr.",
                "Trent McDuffie", "Christian Gonzalez", "Marlon Humphrey",
                "Derwin James", "Kerby Joseph", "Xavier McKinney", "Brian Branch",
                "Kyle Hamilton", "Budda Baker"],
    },
}

_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$")
_INITIALS = re.compile(r"\b([a-z]) (?=[a-z]\b)")


def _norm(name: object) -> str:
    """Normalize a player name for matching across sources: lowercase, straighten
    the apostrophe, drop periods, collapse spaced initials ("a. j." / "t. j." →
    "aj"/"tj") and strip a trailing Jr./III/etc."""
    s = str(name).lower().replace("’", "'").replace(".", "").strip()
    s = re.sub(r"\s+", " ", s)
    s = _INITIALS.sub(r"\1", s)
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


def recognition_scores() -> dict[tuple[str, str], float]:
    """{(normalized_name, side) -> recognition 0..1} from recent All-Pro teams,
    recency-weighted and normalized so a repeat (every-season) selection ≈ 1.0."""
    raw: dict[tuple[str, str], float] = {}
    for year, sides in ALL_PRO.items():
        w = ALL_PRO_RECENCY.get(year, 0.0)
        for side, players in sides.items():
            for player in players:
                key = (_norm(player), side)
                raw[key] = raw.get(key, 0.0) + w
    norm = sum(ALL_PRO_RECENCY.values()) or 1.0
    return {k: min(v / norm, 1.0) for k, v in raw.items()}


def _buzz_index() -> dict[tuple[str, str], float]:
    """{(normalized_name, side) -> buzz 0..1}. A player's buzz is the strongest of
    his current award-market odds (live Kalshi, else snapshot) and his recent
    All-Pro recognition — forward hype *or* proven accolades, whichever is higher."""
    live = dict(fetch_live_buzz())
    manual = _manual_by_award()
    idx: dict[tuple[str, str], float] = {}
    for award in ("MVP", "OPOY", "DPOY"):
        for nm, side, p in live.get(award) or manual.get(award, []):
            key = (nm, side)
            idx[key] = max(idx.get(key, 0.0), float(p))
    for key, r in recognition_scores().items():
        idx[key] = max(idx.get(key, 0.0), r)
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
