# GridironIQ Scouting Agent

A natural-language front door to the warehouse. Ask a cap/roster question in
English; Claude answers it by writing **read-only SQL against the dbt marts** and
explaining the numbers.

```
question ─► Claude (tool-use loop) ──run_sql──► DuckDB warehouse (dbt marts)
                    ▲                               │
                    └──────── rows ◄────────────────┘
         ─► grounded analyst answer + full SQL trace
```

## Why it's built this way

- **Tool, not text-to-SQL-in-one-shot.** Claude gets a `run_sql` tool and the live
  schema, so it can query, read errors, and re-query — grounding every claim in
  real rows instead of hallucinating numbers.
- **Read-only + guarded.** `warehouse.run_sql` opens DuckDB read-only *and* allows
  only a single `SELECT`/`WITH` (keyword-denies `DROP`, `ATTACH`, `COPY`, …), so a
  bad generation can't mutate or escape the warehouse.
- **Every query is traced.** The loop is hand-written so each SQL statement is
  captured in `ScoutResult.trace` — which the Phase 4 eval harness scores for
  correctness and groundedness.

## Use it

```bash
python -m gridiron.agent.scout "which positions do Super Bowl winners overpay for?"
```

```python
from gridiron.agent import ScoutAgent

result = ScoutAgent().ask("Who are the 5 most cap-efficient players right now?")
print(result.answer)
print(result.sql_queries)   # the SQL Claude actually ran
```

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `GRIDIRON_SCOUT_MODEL` | `claude-opus-5` | set `claude-sonnet-4-6` for cheaper eval runs |
| `GRIDIRON_SCOUT_EFFORT` | `medium` | `low`\|`medium`\|`high`\|`xhigh`\|`max` |
| `ANTHROPIC_API_KEY` | — | read from `.env` |

## Files

- `warehouse.py` — schema introspection + the guarded read-only `run_sql`.
- `scout.py` — the `ScoutAgent` tool-use loop, system prompt, and CLI.
