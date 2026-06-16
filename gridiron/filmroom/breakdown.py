"""
Film Room stage 2: turn extracted game metrics into a natural-language report.

Uses the Anthropic Python SDK (``claude-sonnet-4-6``) to write a film-room-style
breakdown of *why a team lost*, grounded in the numbers from
:func:`gridiron.filmroom.pbp_metrics.build_breakdown_payload`. The model is asked
to be specific, tactical, and actionable -- citing the actual metrics, not vibes.
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

SYSTEM_PROMPT = """\
You are a veteran NFL film-room analyst writing a post-game breakdown for a \
coaching staff. You are given structured performance metrics extracted from the \
play-by-play of a single game, framed around the team that LOST.

Write a breakdown that explains *why they lost*, in the voice of a film session:
specific, tactical, and actionable. Rules:
  - Lead with the 2-3 root causes, each tied to a concrete metric from the data.
  - Compare the losing offense to the winning offense where it sharpens the point.
  - Translate numbers into football (e.g. a high pressure-rate-allowed = the \
protection or the QB clock broke down; negative pass EPA with positive rush EPA \
= they abandoned what worked).
  - Call out any metric that is missing/None as "not charted" -- never invent it.
  - End with 3 concrete, position-specific fixes for next week.

Structure: a short headline read, then "What broke down" (bulleted, each with its \
metric), then "Corrections for next week" (3 bullets). Keep it tight -- a coach's \
attention span, not an essay."""


def generate_breakdown(
    payload: dict,
    *,
    model: str = config.ANTHROPIC_MODEL,
    max_tokens: int = config.ANTHROPIC_MAX_TOKENS,
    client: anthropic.Anthropic | None = None,
) -> str:
    """Generate the film-room report for one game's metrics ``payload``.

    Requires ``ANTHROPIC_API_KEY`` in the environment (or a configured client).
    """
    if client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or pass an explicit `client`."
            )
        client = anthropic.Anthropic()

    user_message = _format_payload(payload)
    log.info("Requesting film breakdown for game %s", payload.get("game_id"))
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _format_payload(payload: dict) -> str:
    """Render the metrics payload as a compact, model-readable brief."""
    loser = payload.get("loser")
    winner = payload.get("winner")
    score = payload.get("score", {})
    header = (
        f"GAME: week {payload.get('week')} | {winner} def. {loser} | "
        f"score {json.dumps(score)}\n"
        f"Losing team: {loser}\n"
    )
    metrics = {
        "losing_offense": payload.get("losing_offense"),
        "winning_offense": payload.get("winning_offense"),
        "charting_metrics_pending": payload.get("charting_metrics_pending"),
    }
    return (
        header
        + "\nMETRICS (JSON):\n"
        + json.dumps(metrics, indent=2)
        + "\n\nWrite the film-room breakdown of why "
        + f"{loser} lost."
    )
