"""
Boardroom cap-efficiency analysis.

Reads the loaded Boardroom tables/views and answers the thesis directly:

    "In the salary cap era, which positions truly win championships,
     and are teams paying for it correctly?"

Core outputs:
  * ``champion_premium``         -- how much more/less of the cap SB winners spend
                                    on each position vs. the league average.
  * ``spending_success_corr``    -- correlation of each position's cap share with
                                    reaching / winning the Super Bowl.
  * ``efficiency_verdict``       -- combines the two into an overpaid / underpaid
                                    / fairly-paid label per position.

All shares default to the coverage-adjusted ``cap_pct_norm`` and the post-2011
window, where the OverTheCap source is comprehensive (see README data notes).
"""

from __future__ import annotations

import pandas as pd

from gridiron import db
from gridiron.ingestion.reference import POSITION_GROUP_ORDER

#: Source is comprehensive from the 2011 CBA onward; earlier seasons are sparse.
RELIABLE_START = 2011


def load_team_season(min_season: int = RELIABLE_START) -> pd.DataFrame:
    """Return the team-season feature matrix joined to SB outcomes."""
    return db.query(
        "SELECT * FROM v_team_season WHERE season >= :s ORDER BY season, team",
        s=min_season,
    )


def load_positional_long(min_season: int = RELIABLE_START) -> pd.DataFrame:
    """Return tidy positional spending tagged with SB outcomes."""
    return db.query(
        "SELECT * FROM v_positional_long WHERE season >= :s",
        s=min_season,
    )


def champion_premium(min_season: int = RELIABLE_START,
                     share: str = "cap_pct_norm") -> pd.DataFrame:
    """Average positional share among SB winners vs. the league, with the gap.

    ``premium > 0`` => champions historically spend *more* here than average.
    ``premium < 0`` => champions win while spending *less* here.
    """
    long = load_positional_long(min_season)
    grp = long.groupby("pos_group")
    out = pd.DataFrame({
        "league_avg": grp[share].mean(),
        "finalist_avg": grp.apply(
            lambda d: d.loc[d.sb_appearance == 1, share].mean(), include_groups=False),
        "champion_avg": grp.apply(
            lambda d: d.loc[d.sb_win == 1, share].mean(), include_groups=False),
    })
    out["premium"] = out["champion_avg"] - out["league_avg"]
    return out.sort_values("premium", ascending=False).round(4)


def spending_success_corr(min_season: int = RELIABLE_START) -> pd.DataFrame:
    """Correlation of each position's cap share with postseason success.

    Pearson correlation across all team-seasons between ``pct_<pos>`` and the
    binary outcomes (point-biserial). Positive => more spend tracks with deeper
    runs; near-zero/negative => spend there does not buy championships.
    """
    ts = load_team_season(min_season)
    rows = []
    for pos in POSITION_GROUP_ORDER:
        col = f"pct_{pos}"
        if col not in ts.columns:
            continue
        rows.append({
            "pos_group": pos,
            "corr_appearance": ts[col].corr(ts["sb_appearance"]),
            "corr_win": ts[col].corr(ts["sb_win"]),
        })
    return pd.DataFrame(rows).sort_values("corr_win", ascending=False).round(4)


def efficiency_verdict(min_season: int = RELIABLE_START) -> pd.DataFrame:
    """Combine premium + correlation into a per-position efficiency label.

    Heuristic read of the thesis:
      * champions over-index AND spend tracks winning  -> "worth paying (premium)"
      * champions under-index AND spend doesn't track  -> "overpaid leaguewide"
      * mixed signals                                  -> "fairly paid"
    """
    prem = champion_premium(min_season)["premium"]
    corr = spending_success_corr(min_season).set_index("pos_group")["corr_win"]
    out = pd.DataFrame({"champion_premium": prem, "corr_win": corr})

    def verdict(r: pd.Series) -> str:
        if r.champion_premium > 0.005 and r.corr_win > 0:
            return "underpaid (worth paying up)"
        if r.champion_premium < -0.005 and r.corr_win <= 0:
            return "overpaid leaguewide"
        return "fairly paid"

    out["verdict"] = out.apply(verdict, axis=1)
    return out.sort_values("champion_premium", ascending=False).round(4)


if __name__ == "__main__":  # quick smoke / demo
    pd.set_option("display.width", 160)
    print("\nChampion premium (normalized share, 2011+):")
    print(champion_premium())
    print("\nSpending vs. success correlation (2011+):")
    print(spending_success_corr().to_string(index=False))
    print("\nEfficiency verdict:")
    print(efficiency_verdict())
