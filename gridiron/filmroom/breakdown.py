"""
Film Room stage 2: turn game metrics into a natural-language report.

Uses the Anthropic Python SDK (``claude-sonnet-4-6``, with adaptive thinking so it
reasons through the numbers before writing) in two modes:

  * **post-game** — "why a team lost", from a played game's play-by-play metrics
    (:func:`gridiron.filmroom.pbp_metrics.build_breakdown_payload`).
  * **pre-game**  — a matchup preview from each team's form + roster-strength
    edges (:func:`gridiron.filmroom.matchup.build_preview_payload`).

The mode is read off ``payload["mode"]``. Either way the model is asked to be
specific and tactical — citing the actual numbers, never inventing them.
"""

from __future__ import annotations

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

from gridiron import config

load_dotenv()
log = logging.getLogger(__name__)

SYSTEM_POST = """\
You are a veteran NFL film-room analyst writing a post-game breakdown for a \
coaching staff. You are given structured metrics extracted from the play-by-play \
of a single game (plus player attribution and situational splits), framed around \
the team that LOST.

Write a breakdown that explains *why they lost*, in the voice of a film session:
specific, tactical, and actionable. Rules:
  - Lead with the 2-3 root causes, each tied to a concrete metric from the data.
  - Name names from the attribution (who took the sacks, who turned it over, who \
moved the ball) and compare losing vs. winning offense where it sharpens the point.
  - Translate numbers into football (high pressure-rate-allowed = protection or the \
QB clock broke down; negative pass EPA with positive rush EPA = they abandoned what \
worked; a bad first-half EPA = they got buried early).
  - Call out any metric that is missing/None as "not charted" -- never invent it.
  - End with 3 concrete, position-specific fixes for next week.

Structure: a short headline read, then "What broke down" (bulleted, each with its \
metric), then "Corrections for next week" (3 bullets). Keep it tight."""

SYSTEM_PRE = """\
You are a veteran NFL analyst writing a pre-game matchup preview for a coaching \
staff. You are given each team's season form (offense + defense EPA/efficiency, \
pressure, explosives, turnover margin) and their roster-strength edges by position \
(percentile vs. the league, with the home-minus-away edge). There is no \
play-by-play yet -- this game has not been played.

Write a preview that calls the game, grounded in the numbers. Rules:
  - Open with the headline matchup and which way you lean, with the key reason.
  - Identify the 2-3 decisive edges, each tied to a concrete number (e.g. one \
team's pass-rush percentile vs. the other's pressure-allowed / O-line).
  - Treat large roster-edge and form gaps as the spine; ignore None/missing fields \
rather than inventing them.
  - It's a projection, not a guarantee -- be decisive but honest about variance.

Structure: a headline lean; "Where it's won" (2-3 bulleted edges, each with \
numbers); then a one-line "Key to winning" for each team. Keep it tight."""


def generate_breakdown(
    payload: dict,
    *,
    model: str = config.ANTHROPIC_MODEL,
    max_tokens: int = config.ANTHROPIC_MAX_TOKENS,
    client: anthropic.Anthropic | None = None,
) -> str:
    """Generate the film report for a ``payload`` (pre- or post-game).

    Requires ``ANTHROPIC_API_KEY`` in the environment (or a configured client).
    """
    if client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or pass an explicit `client`."
            )
        client = anthropic.Anthropic()

    mode = payload.get("mode", "post")
    system = SYSTEM_PRE if mode == "pre" else SYSTEM_POST
    user_message = _format_preview(payload) if mode == "pre" else _format_post(payload)
    log.info("Requesting %s-game report for %s", mode,
             payload.get("matchup") or payload.get("game_id"))

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _format_post(payload: dict) -> str:
    """Render the post-game payload as a compact, model-readable brief."""
    loser, winner = payload.get("loser"), payload.get("winner")
    header = (
        f"GAME: week {payload.get('week')} | {winner} def. {loser} | "
        f"score {json.dumps(payload.get('score', {}))}\nLosing team: {loser}\n"
    )
    metrics = {
        "losing_offense": payload.get("losing_offense"),
        "winning_offense": payload.get("winning_offense"),
        "losing_key_players": payload.get("losing_key_players"),
        "winning_key_players": payload.get("winning_key_players"),
        "losing_situational": payload.get("losing_situational"),
        "charting_metrics_pending": payload.get("charting_metrics_pending"),
    }
    return (header + "\nMETRICS (JSON):\n"
            + json.dumps(metrics, indent=2, default=str)
            + f"\n\nWrite the film-room breakdown of why {loser} lost.")


def _format_preview(payload: dict) -> str:
    """Render the pre-game payload as a compact, model-readable brief."""
    home, away = payload.get("home"), payload.get("away")
    header = (f"MATCHUP: {away} @ {home} | week {payload.get('week')} | "
              f"form season {payload.get('form_season')}\n")
    body = {
        "away_form": payload.get("away_form"),
        "home_form": payload.get("home_form"),
        "roster_edges_home_minus_away": payload.get("roster_edges"),
    }
    return (header + "\nDATA (JSON):\n"
            + json.dumps(body, indent=2, default=str)
            + f"\n\nWrite the pre-game preview for {away} @ {home}.")
