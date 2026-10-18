# Scouting Agent — Eval Harness

Proves the AI layer is *reliable*, not just demo-able. Every question in the golden
set is scored automatically on four axes, with **deterministic, free** checks (no
judge API calls) plus an optional LLM-as-judge layer.

## What's measured

| Metric | Question it answers | How (free / deterministic) |
|---|---|---|
| **correct** | Did it get the right answer? | Ground truth is computed **live** from the warehouse via each item's `truth_sql`, then matched against the answer — so the key is never a stale hardcoded number. |
| **grounded** | Are the stated numbers real? | Every number in the answer must appear in the rows the agent retrieved (checked across fraction↔percent scalings). Catches hallucinated figures. |
| **table_used** | Did it query the right data? | The trace SQL must reference the expected table(s). |
| **executed** | Did the SQL run? | At least one trace query succeeded. |

The golden set ([golden_set.json](golden_set.json), 20 items) spans factual lookups,
rankings, era-normalized questions, and **adversarial "no-answer" cases** (concussions,
coach records, 2027 predictions) where the *correct* behavior is to refuse rather than
invent — the single most important thing to test in a data agent.

## Run it

```bash
# Free deterministic scoring, agent under test on Sonnet (cheap):
python -m gridiron.evals.harness --model claude-sonnet-4-6

# Add an optional LLM-as-judge faithfulness score (this one costs judge tokens):
python -m gridiron.evals.harness --model claude-sonnet-4-6 --judge claude-opus-5
```

Results are written to `last_report.md` (human) and `last_report.json` (machine /
CI). In Phase 5 the JSON gates a GitHub Actions check — a regression in agent
quality fails the build, the same way the dbt tests do for data.

## Why deterministic-first

LLM-as-judge is useful for fuzzy quality, but correctness and groundedness for a
SQL agent are *checkable* — so we check them in plain Python. That makes the suite
free, fast, reproducible, and defensible in an interview ("how do you know the
agent is right?" → "ground truth from the warehouse, matched programmatically").
