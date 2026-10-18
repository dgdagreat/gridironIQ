"""Deterministic (free) eval harness for the scouting agent.

For each golden question we run the agent, then score its answer + SQL trace on:

  - correct    : the ground truth (computed live from the warehouse via the item's
                 truth_sql, so it is never a stale hardcoded number) appears in the
                 answer; for adversarial items, the agent refused instead of inventing.
  - grounded   : the numbers the agent states are actually present in the rows it
                 retrieved (checked across fraction<->percent scalings).
  - table_used : the agent queried the table(s) the question is about.
  - executed   : at least one query ran without error (or, for adversarial items,
                 the agent did not fabricate data).

Scoring is pure Python — no judge API calls — so a full run costs only the agent's
own tokens. Pass judge_model=... to add an optional LLM-as-judge faithfulness score.

CLI:
    python -m gridiron.evals.harness                       # deterministic only
    python -m gridiron.evals.harness --model claude-sonnet-4-6
    python -m gridiron.evals.harness --judge claude-opus-5 # + LLM-as-judge
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from gridiron.agent import warehouse
from gridiron.agent.scout import ScoutAgent, ScoutResult, ToolCall

HERE = Path(__file__).resolve().parent
GOLDEN_PATH = HERE / "golden_set.json"
REPORT_MD = HERE / "last_report.md"
REPORT_JSON = HERE / "last_report.json"
RAW_JSON = HERE / "last_run.json"  # raw agent outputs (answers + traces) for free re-scoring

# Match standalone numbers (optionally with a magnitude/unit suffix like 255.4M or
# 8.3%), but NOT digits fused into a word like "49ers" or "1st" — those are
# names/ordinals, not data claims. Dashes are normalized to ASCII minus first.
_NUM = re.compile(
    r"(?<![A-Za-z0-9.])-?\$?\d[\d,]*(?:\.\d+)?(?:[MBK]|bn|m|pp|%)?(?![A-Za-z0-9])"
)
_REFUSAL = re.compile(
    r"\b(no|not|cannot|can't|can not|unable|don't have|doesn't|does not|isn't|"
    r"aren't|no data|not available|no information|not tracked|not (in|part of)|"
    r"outside|beyond|no way to|can't answer|unavailable)\b",
    re.IGNORECASE,
)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _numbers(text: str) -> list[float]:
    # Normalize the Unicode minus (U+2212) and en/em dashes (U+2013/U+2014) the
    # model uses interchangeably for "minus", so "−2.08" / "–2.08" parse negative.
    text = (text or "").replace("−", "-").replace("–", "-").replace("—", "-")
    out = []
    for m in _NUM.findall(text):
        core = re.sub(r"[^\d.\-]", "", m)  # drop $, commas, unit suffix, %
        try:
            out.append(float(core))
        except ValueError:
            pass
    return out


def _trace_numbers(result: ScoutResult) -> list[float]:
    nums: list[float] = []
    for call in result.trace:
        for row in call.rows:
            for cell in row:
                if isinstance(cell, (int, float)):
                    nums.append(float(cell))
                elif isinstance(cell, str):
                    nums.extend(_numbers(cell))
    return nums


def _backed(target: float, pool: list[float]) -> bool:
    """Is `target` present in `pool`, allowing fraction<->percent scaling + rounding?"""
    for scale in (1.0, 0.01, 100.0):
        t = target * scale
        tol = max(0.05, abs(t) * 0.03)  # tolerance relative to the SCALED value
        for p in pool:
            if abs(p - t) <= tol:
                return True
    return False


@dataclass
class ItemScore:
    id: str
    kind: str
    question: str
    answer: str
    n_queries: int
    correct: bool
    grounded: bool
    grounded_ratio: float
    table_used: bool
    executed: bool
    expected: list[str] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    judge_score: int | None = None
    judge_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.correct and self.grounded


@dataclass
class EvalReport:
    model: str
    n_items: int
    correct_rate: float
    grounded_rate: float
    table_rate: float
    executed_rate: float
    pass_rate: float
    items: list[ItemScore]
    judge_model: str | None = None
    judge_mean: float | None = None


def _expected_values(item: dict[str, Any]) -> list[str]:
    if "expected_labels" in item:
        return [str(x) for x in item["expected_labels"]]
    if "truth_sql" not in item:
        return []
    con = duckdb.connect(str(warehouse.WAREHOUSE_PATH), read_only=True)
    try:
        rows = con.execute(item["truth_sql"]).fetchall()
    finally:
        con.close()
    return [str(v) for row in rows for v in row]


def _label_matches(expected: list[str], answer: str, tol: float) -> bool:
    ans = answer.lower()
    for exp in expected:
        try:  # numeric expected -> tolerant number match
            target = float(exp)
            if not _backed(target, _numbers(answer)) and not any(
                abs(n - target) <= tol for n in _numbers(answer)
            ):
                return False
        except ValueError:  # string expected -> substring
            if exp.lower() not in ans:
                return False
    return True


def score_item(
    item: dict[str, Any], result: ScoutResult, expected: list[str] | None = None
) -> ItemScore:
    answer = result.answer
    kind = item["kind"]
    sql = result.sql_queries
    # `expected` (ground truth) may be supplied pre-computed so re-scoring needs no
    # warehouse; otherwise derive it live from the item's truth_sql.
    if expected is None:
        expected = _expected_values(item)
    tol = float(item.get("tol", 0.4))

    ans_nums = _numbers(answer)
    # A number is "grounded" if it appears in the retrieved rows, in the SQL the
    # agent ran (a filter literal it used), or in the question itself (the user
    # supplied it) — none of those are hallucinations.
    pool = (
        _trace_numbers(result)
        + _numbers(item["question"])
        + [n for c in result.trace for n in _numbers(c.sql)]
    )
    backed = [n for n in ans_nums if _backed(n, pool)]
    grounded_ratio = 1.0 if not ans_nums else len(backed) / len(ans_nums)

    if kind == "adversarial":
        # The correct behavior is to REFUSE — there is no data to answer with, so
        # groundedness of any incidental numbers (table examples, flags) is moot.
        refused = bool(_REFUSAL.search(answer))
        correct = refused
        grounded = refused or grounded_ratio >= 0.5
        table_used = True  # not applicable
        executed = not any(c.error for c in result.trace) or len(result.trace) == 0
    else:
        correct = bool(expected) and _label_matches(expected, answer, tol)
        # Grounded if the answer's numbers are backed by retrieved rows — OR the
        # expected figure(s) are backed, tolerating extra descriptive numbers
        # (e.g. an enumerated list) that the query didn't return.
        expected_nums = [float(e) for e in expected if _is_float(e)]
        grounded = grounded_ratio >= 0.6 or (
            bool(expected_nums) and all(_backed(e, pool) for e in expected_nums)
        )
        wanted = item.get("expected_tables", [])
        table_used = any(
            any(t in q for t in wanted) for q in sql
        ) if wanted else True
        executed = any(not c.error for c in result.trace)

    return ItemScore(
        id=item["id"],
        kind=kind,
        question=item["question"],
        answer=answer,
        n_queries=len(sql),
        correct=correct,
        grounded=grounded,
        grounded_ratio=round(grounded_ratio, 3),
        table_used=table_used,
        executed=executed,
        expected=expected,
        sql=sql,
    )


JUDGE_SYSTEM = (
    "You are a strict evaluator of an NFL analytics assistant. Given the question, "
    "the data rows the assistant retrieved, and its answer, rate how faithful the "
    "answer is to the retrieved data on a 1-5 scale (5 = every claim supported, "
    "1 = fabricated or contradicted). Reply as JSON: {\"score\": int, \"reason\": str}."
)


def _judge(item: dict[str, Any], result: ScoutResult, model: str) -> dict[str, Any]:
    import anthropic

    rows = "\n\n".join(
        f"SQL: {c.sql}\nROWS: {c.rows[:20]}" for c in result.trace
    ) or "(no queries run)"
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=1000,
        system=JUDGE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"QUESTION:\n{item['question']}\n\n"
                    f"RETRIEVED DATA:\n{rows}\n\n"
                    f"ASSISTANT ANSWER:\n{result.answer}"
                ),
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        payload = json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0))
        return {"score": int(payload["score"]), "reason": str(payload.get("reason", ""))}
    except Exception:  # noqa: BLE001 - judge returned unparseable JSON; degrade gracefully
        return {"score": None, "reason": text[:200]}


def run_evals(
    model: str | None = None,
    judge_model: str | None = None,
    golden_path: Path = GOLDEN_PATH,
) -> EvalReport:
    golden = json.loads(golden_path.read_text())
    agent = ScoutAgent(model=model) if model else ScoutAgent()

    scores: list[ItemScore] = []
    raw: list[dict[str, Any]] = []
    for i, item in enumerate(golden, 1):
        print(f"[{i:>2}/{len(golden)}] {item['id']} ...", flush=True)
        result = agent.ask(item["question"])
        expected = _expected_values(item)  # ground truth from the warehouse, once
        raw.append({
            "id": item["id"],
            "answer": result.answer,
            "expected": expected,
            "trace": [asdict(c) for c in result.trace],
        })
        score = score_item(item, result, expected)
        if judge_model and item["kind"] != "adversarial":
            j = _judge(item, result, judge_model)
            score.judge_score, score.judge_reason = j["score"], j["reason"]
        scores.append(score)

    RAW_JSON.write_text(json.dumps({"model": agent.model, "runs": raw}, indent=2))
    report = _aggregate(agent.model, scores, judge_model)
    _write_reports(report)
    return report


def _aggregate(
    model: str, scores: list[ItemScore], judge_model: str | None
) -> EvalReport:
    n = len(scores)
    rate = lambda pred: round(sum(1 for s in scores if pred(s)) / n, 3)
    judged = [s.judge_score for s in scores if s.judge_score is not None]
    return EvalReport(
        model=model,
        n_items=n,
        correct_rate=rate(lambda s: s.correct),
        grounded_rate=rate(lambda s: s.grounded),
        table_rate=rate(lambda s: s.table_used),
        executed_rate=rate(lambda s: s.executed),
        pass_rate=rate(lambda s: s.passed),
        items=scores,
        judge_model=judge_model,
        judge_mean=round(sum(judged) / len(judged), 2) if judged else None,
    )


def rescore(golden_path: Path = GOLDEN_PATH) -> EvalReport:
    """Re-score the last run's persisted answers/traces WITHOUT calling the model.

    Lets us iterate on scoring logic for free after a single paid run.
    """
    if not RAW_JSON.exists():
        raise FileNotFoundError(f"{RAW_JSON} not found — run the suite once first.")
    raw = json.loads(RAW_JSON.read_text())
    golden = {it["id"]: it for it in json.loads(golden_path.read_text())}

    scores: list[ItemScore] = []
    for rec in raw["runs"]:
        item = golden[rec["id"]]
        trace = [
            ToolCall(
                sql=c["sql"],
                row_count=c["row_count"],
                error=c["error"],
                columns=c["columns"],
                rows=c["rows"],
            )
            for c in rec["trace"]
        ]
        result = ScoutResult(item["question"], rec["answer"], trace, len(trace))
        scores.append(score_item(item, result, rec.get("expected")))

    report = _aggregate(raw.get("model", "unknown"), scores, None)
    _write_reports(report)
    return report


def _write_reports(report: EvalReport) -> None:
    REPORT_JSON.write_text(json.dumps(asdict(report), indent=2))
    lines = [
        "# Scouting Agent — Eval Report",
        "",
        f"- **Model under test:** `{report.model}`",
        f"- **Golden questions:** {report.n_items}",
        f"- **Pass rate (correct AND grounded):** {report.pass_rate:.0%}",
        (f"- **Correct:** {report.correct_rate:.0%} · **Grounded:** {report.grounded_rate:.0%}"
        f" · **Right table:** {report.table_rate:.0%} · **Executed:** {report.executed_rate:.0%}"),
    ]
    if report.judge_model:
        lines.append(
            f"- **LLM judge ({report.judge_model}) mean faithfulness:** "
            f"{report.judge_mean}/5"
        )
    lines += ["", "| id | kind | correct | grounded | table | q | ", "|---|---|:-:|:-:|:-:|:-:|"]
    for s in report.items:
        c = "✅" if s.correct else "❌"
        g = "✅" if s.grounded else "❌"
        t = "✅" if s.table_used else "❌"
        lines.append(f"| {s.id} | {s.kind} | {c} | {g} | {t} | {s.n_queries} |")
    REPORT_MD.write_text("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run scouting-agent evals.")
    ap.add_argument("--model", default=None, help="agent-under-test model id")
    ap.add_argument("--judge", default=None, help="optional LLM-as-judge model id")
    ap.add_argument(
        "--rescore",
        action="store_true",
        help="re-score the last run's persisted answers, no model calls",
    )
    ap.add_argument("--min-pass", type=float, default=None, help="fail if pass_rate below")
    ap.add_argument("--min-grounded", type=float, default=None, help="fail if grounded_rate below")
    args = ap.parse_args(argv)

    report = rescore() if args.rescore else run_evals(model=args.model, judge_model=args.judge)
    print("\n" + REPORT_MD.read_text())
    print(f"(reports written to {REPORT_MD.name} / {REPORT_JSON.name})")

    # Quality gate — lets CI fail on an agent-quality regression.
    failures = []
    if args.min_pass is not None and report.pass_rate < args.min_pass:
        failures.append(f"pass_rate {report.pass_rate:.2f} < {args.min_pass}")
    if args.min_grounded is not None and report.grounded_rate < args.min_grounded:
        failures.append(f"grounded_rate {report.grounded_rate:.2f} < {args.min_grounded}")
    if failures:
        print("QUALITY GATE FAILED: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
