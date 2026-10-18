"""The eval scorer's number parsing, groundedness, and refusal logic."""
import pytest

from gridiron.agent.scout import ScoutResult, ToolCall
from gridiron.evals import harness as h


@pytest.mark.parametrize(
    "text,expected",
    [
        ("KC beat the 49ers (SF) in 2023", [2023.0]),          # 49ers is not "4"/"49"
        ("EDGE premium is −2.08 pp, or 2.08 below", [-2.08, 2.08]),  # U+2212 minus
        ("EDGE premium is –2.08 pp", [-2.08]),                 # en-dash minus
        ("cap was $255.4M in 2024", [255.4, 2024.0]),          # unit suffix
        ("8.3% over 2011–2024", [8.3, 2011.0, 2024.0]),        # percent + range
        ("their 4th title", []),                               # ordinal, not data
    ],
)
def test_number_parsing(text, expected):
    assert h._numbers(text) == expected


def test_backed_handles_fraction_percent_scaling():
    assert h._backed(8.3, [0.083])   # answer in %, data as fraction
    assert h._backed(0.083, [8.3])
    assert not h._backed(42.0, [7.0, 100.0])  # unrelated numbers, no scaling match


def _result(question, answer, sql, rows):
    trace = [ToolCall(sql=sql, row_count=len(rows), error=None, columns=["c"], rows=rows)]
    return ScoutResult(question, answer, trace, 1)


def test_label_answer_scores_correct_and_grounded():
    item = {
        "id": "t", "kind": "label", "question": "Best value position?",
        "expected_tables": ["value_board"], "expected_labels": ["WR"],
    }
    res = _result("Best value position?", "The best value is WR (Puka Nacua).",
                  "SELECT pos_group FROM raw.value_board", [["WR"]])
    score = h.score_item(item, res)
    assert score.correct and score.table_used and score.executed


def test_adversarial_refusal_is_correct():
    item = {"id": "a", "kind": "adversarial", "question": "Ticket prices?"}
    res = _result("Ticket prices?", "That data is not available in this warehouse.", "", [])
    score = h.score_item(item, res)
    assert score.correct and score.grounded


def test_adversarial_hallucination_is_wrong():
    item = {"id": "a", "kind": "adversarial", "question": "Ticket prices?"}
    res = _result("Ticket prices?", "The average ticket price was $312.", "", [])
    score = h.score_item(item, res)
    assert not score.correct  # invented a figure instead of refusing
