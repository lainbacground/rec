from __future__ import annotations

from dataclasses import asdict

import pytest

from rec.data_loader import dataset_from_records
from rec.metrics import evaluate_metrics
from rec.validation import validate_dataset


def record(response_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "response_id": response_id,
        "prompt_id": f"prompt-{response_id}",
        "prompt": "Prompt",
        "model_response": "Response",
        "model_name": "model-a",
        "category": "facts",
        "human_score": 3,
        "ai_score": 3,
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


def evaluate(*rows: dict[str, object]):
    columns = tuple(record("schema").keys())
    dataset = dataset_from_records(rows, columns=columns)
    return evaluate_metrics(validate_dataset(dataset))


def test_adds_all_row_level_comparison_fields_without_mutating_input() -> None:
    source = record("1", human_score=2, ai_score=4)

    audit = evaluate(source)

    assert audit.rows[0]["score_difference"] == 2
    assert audit.rows[0]["absolute_score_difference"] == 2
    assert audit.rows[0]["exact_agreement"] is False
    assert audit.rows[0]["within_one_agreement"] is False
    assert "score_difference" not in source


def test_calculates_all_overall_metrics_and_response_denominators() -> None:
    audit = evaluate(
        record("1", prompt_id="shared", human_score=3, ai_score=3),
        record(
            "2",
            prompt_id="shared",
            human_score=2,
            ai_score=3,
            error_severity="critical",
        ),
        record("3", human_score=5, ai_score=3),
        record("4", human_score=2, ai_score=4),
    )

    assert asdict(audit.overall) == {
        "number_of_prompts": 3,
        "number_of_responses": 4,
        "average_human_score": 3.0,
        "average_ai_score": 3.25,
        "exact_agreement_rate": 0.25,
        "agreement_within_one_point": 0.5,
        "signed_evaluator_bias": 0.25,
        "mean_absolute_score_difference": 1.25,
        "ai_overrating_rate": 0.5,
        "ai_underrating_rate": 0.25,
        "critical_failure_count": 1,
        "critical_failure_rate": 0.25,
    }


def test_builds_summaries_for_every_requested_dimension() -> None:
    audit = evaluate(
        record("1", model_name="model-a", category="facts", error_type=None),
        record(
            "2",
            model_name="model-b",
            category="code",
            error_type="incorrect",
            error_severity="high",
            human_score=2,
            ai_score=4,
        ),
        record(
            "3",
            model_name="model-b",
            category="code",
            error_type="incorrect",
            error_severity="critical",
            human_score=4,
            ai_score=3,
        ),
    )

    assert audit.by_model["model-b"].number_of_responses == 2
    assert audit.by_model["model-b"].signed_evaluator_bias == 0.5
    assert audit.by_category["code"].average_human_score == 3.0
    assert audit.by_error_type["incorrect"].ai_overrating_rate == 0.5
    assert audit.by_error_type[None].number_of_responses == 1
    assert audit.by_severity["critical"].critical_failure_rate == 1.0


def test_valid_empty_dataset_has_explicit_undefined_rates_and_no_groups() -> None:
    audit = evaluate()

    assert audit.overall.number_of_prompts == 0
    assert audit.overall.number_of_responses == 0
    assert audit.overall.critical_failure_count == 0
    for name, value in asdict(audit.overall).items():
        if name not in {
            "number_of_prompts",
            "number_of_responses",
            "critical_failure_count",
        }:
            assert value is None
    assert audit.by_model == {}
    assert audit.by_category == {}
    assert audit.by_error_type == {}
    assert audit.by_severity == {}


def test_rejects_unvalidated_rows_with_actionable_error() -> None:
    invalid = validate_dataset(dataset_from_records([record("1", ai_score=9)]))

    with pytest.raises(ValueError, match="valid ValidationResult"):
        evaluate_metrics(invalid)

