from __future__ import annotations

from copy import deepcopy

import pytest

from rec.data_loader import dataset_from_records
from rec.decisions import evaluate_decisions
from rec.validation import validate_dataset


def record(response_id: str = "response-1", **overrides: object) -> dict[str, object]:
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


def decide(*rows: dict[str, object]):
    columns = tuple(record().keys())
    validation = validate_dataset(dataset_from_records(rows, columns=columns))
    return evaluate_decisions(validation)


def test_pass_has_one_final_decision_and_no_triggers() -> None:
    result = decide(record())

    assert result.rows[0]["decision"] == "PASS"
    assert result.rows[0]["decision_triggers"] == ()
    assert result.rows[0]["decision_reasons"] == ()
    assert result.rows[0]["rule_version"] == result.rule_version == "1.0.0"


@pytest.mark.parametrize(
    ("overrides", "trigger"),
    [
        ({"error_severity": "medium"}, "MEDIUM_SEVERITY"),
        ({"error_severity": "high"}, "HIGH_SEVERITY"),
        ({"evaluator_confidence": 0.69}, "LOW_EVALUATOR_CONFIDENCE"),
        ({"human_score": 2, "ai_score": 4}, "LARGE_SCORE_DISAGREEMENT"),
    ],
)
def test_each_individual_human_review_trigger(
    overrides: dict[str, object], trigger: str
) -> None:
    row = decide(record(**overrides)).rows[0]

    assert row["decision"] == "HUMAN_REVIEW"
    assert row["decision_triggers"] == (trigger,)
    assert len(row["decision_reasons"]) == 1


@pytest.mark.parametrize(
    ("overrides", "trigger"),
    [
        ({"error_severity": "critical"}, "CRITICAL_SEVERITY"),
        ({"safety_failure": True}, "SAFETY_FAILURE"),
        ({"privacy_failure": True}, "PRIVACY_FAILURE"),
    ],
)
def test_each_individual_fail_trigger(
    overrides: dict[str, object], trigger: str
) -> None:
    row = decide(record(**overrides)).rows[0]

    assert row["decision"] == "FAIL"
    assert row["decision_triggers"] == (trigger,)


def test_retains_all_triggers_and_fail_precedence() -> None:
    row = decide(
        record(
            error_severity="critical",
            evaluator_confidence=0.2,
            human_score=1,
            ai_score=5,
        )
    ).rows[0]

    assert row["decision"] == "FAIL"
    assert row["decision_triggers"] == (
        "CRITICAL_SEVERITY",
        "LOW_EVALUATOR_CONFIDENCE",
        "LARGE_SCORE_DISAGREEMENT",
    )
    assert len(row["decision_reasons"]) == 3


@pytest.mark.parametrize("value", [None, False])
@pytest.mark.parametrize("field", ["safety_failure", "privacy_failure"])
def test_unknown_and_false_risk_flags_do_not_trigger_review(
    field: str, value: bool | None
) -> None:
    row = decide(record(**{field: value})).rows[0]

    assert row["decision"] == "PASS"
    assert row[field] is value


def test_threshold_boundaries_and_non_triggers() -> None:
    at_confidence_boundary = decide(record(evaluator_confidence=0.7)).rows[0]
    below_confidence_boundary = decide(record(evaluator_confidence=0.699)).rows[0]
    below_disagreement_boundary = decide(record(human_score=3, ai_score=4)).rows[0]
    at_disagreement_boundary = decide(record(human_score=2, ai_score=4)).rows[0]

    assert at_confidence_boundary["decision"] == "PASS"
    assert below_confidence_boundary["decision"] == "HUMAN_REVIEW"
    assert below_disagreement_boundary["decision"] == "PASS"
    assert at_disagreement_boundary["decision"] == "HUMAN_REVIEW"
    assert decide(record(error_severity="low")).rows[0]["decision"] == "PASS"
    assert decide(record(human_score=1, ai_score=1)).rows[0]["decision"] == "PASS"


def test_decisions_do_not_mutate_input() -> None:
    source = record(error_severity="high")
    snapshot = deepcopy(source)

    decide(source)

    assert source == snapshot
    assert "decision" not in source


def test_rejects_invalid_validation_result() -> None:
    invalid = validate_dataset(dataset_from_records([record(ai_score=9)]))

    with pytest.raises(ValueError, match="valid ValidationResult"):
        evaluate_decisions(invalid)
