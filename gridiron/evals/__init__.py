"""Evaluation harness for the GridironIQ scouting agent.

Deterministic, reproducible scoring (correctness / groundedness / table-usage /
refusal) over a golden question set — plus an optional LLM-as-judge layer.
"""
from gridiron.evals.harness import EvalReport, ItemScore, run_evals

__all__ = ["EvalReport", "ItemScore", "run_evals"]
