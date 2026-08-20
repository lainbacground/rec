from __future__ import annotations

from copy import deepcopy

from rec.data_loader import dataset_from_records
from rec.decisions import evaluate_decisions
from rec.review_queue import build_review_queue
from rec.validation import validate_dataset


def record(response_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "response_id": response_id,
        "prompt_id": f"prompt-{response_id}",
        "prompt": "Prompt",
        "model_response": "Response",
        "model_name": "model-a",
        "category": "facts",
        "human_score": 4,
        "ai_score": 4,
        "evaluator_confidence": 0.9,
        "error_severity": "none",
        "error_type": None,
        "safety_failure": False,
        "privacy_failure": False,
        "human_notes": None,
        "review_status": None,
    }
    row.update(overrides)
    return row


def queue(*rows: dict[str, object]):
    columns = tuple(record("schema").keys())
    validation = validate_dataset(dataset_from_records(rows, columns=columns))
    return build_review_queue(evaluate_decisions(validation))


def test_includes_review_and_fail_but_excludes_pass() -> None:
    result = queue(
        record("pass"),
        record("review", error_severity="medium"),
        record("fail", privacy_failure=True),
    )

    assert [item.record["response_id"] for item in result] == ["fail", "review"]
    assert result[0].record["decision_reasons"]
    assert result[0].priority_reasons


def test_priority_order_is_deterministic_and_component_based() -> None:
    result = queue(
        record("low-confidence", evaluator_confidence=0.2),
        record("medium", error_severity="medium"),
        record("high", error_severity="high"),
        record("critical", error_severity="critical"),
        record("risk", safety_failure=True),
    )

    assert [item.record["response_id"] for item in result] == [
        "critical",
        "risk",
        "high",
        "medium",
        "low-confidence",
    ]
    assert result[0].priority.severity_rank == 4
    assert "Error severity is critical." in result[0].priority_reasons
    assert "A safety failure is confirmed." in result[1].priority_reasons


def test_disagreement_then_confidence_break_priority_ties() -> None:
    result = queue(
        record("difference-2", human_score=2, ai_score=4, evaluator_confidence=0.4),
        record("difference-3", human_score=1, ai_score=4, evaluator_confidence=0.6),
        record("lower-confidence", human_score=2, ai_score=4, evaluator_confidence=0.3),
    )

    assert [item.record["response_id"] for item in result] == [
        "difference-3",
        "lower-confidence",
        "difference-2",
    ]


def test_exact_ties_preserve_source_order() -> None:
    result = queue(
        record("first", error_severity="medium"),
        record("second", error_severity="medium"),
    )

    assert [item.record["response_id"] for item in result] == ["first", "second"]
    assert [item.source_index for item in result] == [0, 1]


def test_queue_does_not_mutate_source_records_or_decision_rows() -> None:
    source = record("review", error_severity="high")
    source_snapshot = deepcopy(source)
    columns = tuple(source.keys())
    decisions = evaluate_decisions(
        validate_dataset(dataset_from_records([source], columns=columns))
    )
    decision_snapshot = deepcopy(decisions.rows)

    build_review_queue(decisions)

    assert source == source_snapshot
    assert decisions.rows == decision_snapshot
    assert "priority_reasons" not in decisions.rows[0]
