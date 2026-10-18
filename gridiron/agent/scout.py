"""The GridironIQ scouting agent.

A natural-language front door to the warehouse: Claude is given a `run_sql` tool
(read-only, guarded — see warehouse.py) plus the live schema, and answers cap /
roster questions by querying the dbt marts and explaining the numbers.

The loop is hand-written (not the SDK tool runner) so every SQL statement Claude
runs is captured in a trace — which Phase 4's eval harness scores.

CLI:
    python -m gridiron.agent.scout "which positions do Super Bowl winners overpay for?"
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import anthropic
from dotenv import load_dotenv

from gridiron.agent import warehouse

load_dotenv()

SCOUT_MODEL = os.getenv("GRIDIRON_SCOUT_MODEL", "claude-opus-5")
SCOUT_EFFORT = os.getenv("GRIDIRON_SCOUT_EFFORT", "medium")  # low|medium|high|xhigh|max
MAX_TOKENS = 16000
MAX_STEPS = 6  # tool round-trips before we stop

# Domain semantics the schema alone doesn't convey. Keeps the SQL correct.
SEMANTIC_NOTES = """\
Key facts about this warehouse (an NFL salary-cap analytics platform):
- `main.*` are the dbt marts (query these first); `raw.*` are landed source tables.
- Cap shares (cap_pct, pct_qb, ...) are FRACTIONS of the league cap (0..1), not
  percentages. Multiply by 100 to present a percent.
- pos_group is one of: QB, RB, WR, TE, OL, IDL, EDGE, LB, CB, S, SPEC, UNK.
- main.mart_position_success is the headline: champion_premium = how much more (or
  less, if negative) Super Bowl winners spend at a position vs. the league average.
- main.fct_team_season = one row per team-season with positional cap-share features
  (pct_*) and the SB target (sb_win, sb_appearance).
- Outcome analysis must use FINALIZED seasons only. Seasons after 2024 are forward
  cap projections (partial rosters, no real result). The cap source is reliable from
  2011 on. When modeling outcomes, filter season BETWEEN 2011 AND 2024.
- main.mart_positional_era_avg gives era-aware positional baselines.
- raw.value_board ranks cap-efficient players; raw.roster_strength has unit grades.
"""

SYSTEM_TEMPLATE = """\
You are GridironIQ's scouting analyst. You answer NFL salary-cap and roster
questions by querying a DuckDB warehouse with the `run_sql` tool and explaining
what the numbers mean.

{semantics}

Warehouse schema (schema.table(columns)):
{schema}

How to work:
- Always base claims on data you retrieved with run_sql — never invent numbers.
- Prefer the `main` marts. Write standard DuckDB SQL. One SELECT per call.
- If a query errors, read the message and try again with corrected SQL.
- When you have the answer, give a concise analyst response: lead with the direct
  answer, cite the key figures (as percentages where they are cap shares), and note
  any important caveat (e.g. small sample, projection seasons excluded).
"""

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run a single read-only SELECT query against the GridironIQ DuckDB "
        "warehouse and get the rows back as a table. Only SELECT/WITH is allowed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single DuckDB SELECT (or WITH ... SELECT) query.",
            }
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
}


@dataclass
class ToolCall:
    sql: str
    row_count: int
    error: str | None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


@dataclass
class ScoutResult:
    question: str
    answer: str
    trace: list[ToolCall] = field(default_factory=list)
    steps: int = 0

    @property
    def sql_queries(self) -> list[str]:
        return [t.sql for t in self.trace]


class ScoutAgent:
    def __init__(self, model: str = SCOUT_MODEL, effort: str = SCOUT_EFFORT):
        self.model = model
        self.effort = effort
        self._client = anthropic.Anthropic()
        self._system = SYSTEM_TEMPLATE.format(
            semantics=SEMANTIC_NOTES, schema=warehouse.schema_text()
        )

    def ask(self, question: str) -> ScoutResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        trace: list[ToolCall] = []

        for step in range(1, MAX_STEPS + 1):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                system=self._system,
                tools=[RUN_SQL_TOOL],
                messages=messages,
            )
            # Preserve full content (incl. thinking + tool_use) for the next turn.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                answer = "".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                return ScoutResult(question, answer, trace, step)

            # Execute every tool_use block; return all results in one user message.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                sql = block.input.get("sql", "") if isinstance(block.input, dict) else ""
                result = warehouse.run_sql(sql)
                trace.append(
                    ToolCall(
                        sql=sql,
                        row_count=result.row_count,
                        error=result.error,
                        columns=result.columns,
                        rows=result.rows,
                    )
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.to_markdown(),
                        "is_error": result.error is not None,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return ScoutResult(
            question,
            "(stopped: reached the maximum number of query steps)",
            trace,
            MAX_STEPS,
        )


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m gridiron.agent.scout "your question"')
        return 2
    question = " ".join(argv)
    agent = ScoutAgent()
    result = agent.ask(question)

    print(f"\nQ: {question}\n")
    for i, call in enumerate(result.trace, 1):
        status = f"ERROR: {call.error}" if call.error else f"{call.row_count} rows"
        print(f"  [sql {i}] ({status})")
        print("    " + call.sql.strip().replace("\n", "\n    "))
    print(f"\nA: {result.answer}\n")
    print(f"({result.steps} step(s), {len(result.trace)} query(ies), model={agent.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
