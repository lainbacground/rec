from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from rec.data_loader import dataset_from_records
from rec.reporting import generate_audit_outputs
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


def validation(*rows: dict[str, object]):
    columns = tuple(record("schema").keys())
    return validate_dataset(dataset_from_records(rows, columns=columns))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def test_creates_all_outputs_with_expected_columns_and_values(tmp_path: Path) -> None:
    result = generate_audit_outputs(
        validation(
            record("pass"),
            record(
                "review",
                error_severity="high",
                evaluator_confidence=0.4,
                human_score=2,
                ai_score=4,
            ),
            record("fail", privacy_failure=True, error_severity="critical"),
        ),
        tmp_path / "outputs",
        run_metadata={"Dataset name": "test fixture", "Run identifier": "run-001"},
    )

    assert len(result.all_files) == 11
    assert all(path.is_file() and path.stat().st_size > 0 for path in result.all_files)
    evaluated = read_csv(result.evaluated_responses)
    assert {
        "response_id",
        "score_difference",
        "absolute_score_difference",
        "exact_agreement",
        "within_one_agreement",
        "decision",
        "decision_triggers",
        "decision_reasons",
        "rule_version",
        "priority_decision_tier",
        "priority_reasons",
    }.issubset(evaluated[0])
    assert evaluated[0]["priority_decision_tier"] == ""
    assert evaluated[1]["rule_version"] == "1.0.0"

    overall = read_csv(result.overall_summary)[0]
    assert overall["number_of_responses"] == "3"
    assert overall["critical_failure_count"] == "1"
    assert overall["rule_version"] == "1.0.0"
    model = read_csv(result.model_summary)[0]
    assert model["model_name"] == "model-a"
    assert model["number_of_responses"] == "3"
    assert read_csv(result.category_summary)[0]["category"] == "facts"
    assert {row["error_type"] for row in read_csv(result.error_summary)} == {""}
    assert {row["error_severity"] for row in read_csv(result.severity_summary)} == {
        "critical",
        "high",
        "none",
    }


def test_queue_order_and_json_reason_serialization_are_preserved(tmp_path: Path) -> None:
    result = generate_audit_outputs(
        validation(
            record("review", error_severity="medium"),
            record(
                "fail",
                privacy_failure=True,
                evaluator_confidence=0.3,
                human_score=1,
                ai_score=5,
            ),
        ),
        tmp_path / "outputs",
    )

    queue = read_csv(result.human_review_queue)
    assert [row["response_id"] for row in queue] == ["fail", "review"]
    assert json.loads(queue[0]["decision_triggers"]) == [
        "PRIVACY_FAILURE",
        "LOW_EVALUATOR_CONFIDENCE",
        "LARGE_SCORE_DISAGREEMENT",
    ]
    assert len(json.loads(queue[0]["decision_reasons"])) == 3
    assert json.loads(queue[0]["priority_reasons"])


def test_empty_valid_dataset_writes_headers_report_and_figures(tmp_path: Path) -> None:
    result = generate_audit_outputs(validation(), tmp_path / "outputs")

    assert read_csv(result.evaluated_responses) == []
    assert read_csv(result.human_review_queue) == []
    assert "decision_reasons" in result.evaluated_responses.read_text(encoding="utf-8")
    assert "priority_reasons" in result.human_review_queue.read_text(encoding="utf-8")
    overall = read_csv(result.overall_summary)[0]
    assert overall["number_of_responses"] == "0"
    assert overall["average_human_score"] == ""
    assert read_csv(result.model_summary) == []
    report = result.audit_summary.read_text(encoding="utf-8")
    assert "**0 responses**" in report
    assert "Exact evaluator agreement was **N/A**" in report
    assert all(path.stat().st_size > 0 for path in result.figures)


def test_source_data_is_immutable_and_repeated_runs_are_deterministic(
    tmp_path: Path,
) -> None:
    source = record("review", error_severity="high")
    snapshot = deepcopy(source)
    valid = validation(source)
    output_dir = tmp_path / "outputs"

    first = generate_audit_outputs(valid, output_dir, {"Run identifier": "stable"})
    first_bytes = {path.name: path.read_bytes() for path in first.all_files}
    second = generate_audit_outputs(valid, output_dir, {"Run identifier": "stable"})

    assert source == snapshot
    assert first_bytes == {path.name: path.read_bytes() for path in second.all_files}


def test_markdown_contains_required_methodology_and_limitations(tmp_path: Path) -> None:
    result = generate_audit_outputs(
        validation(record("fail", safety_failure=True)),
        tmp_path / "outputs",
    )
    report = result.audit_summary.read_text(encoding="utf-8")

    for required_text in (
        "## Dataset and run metadata",
        "**Rule version:** 1.0.0",
        "## Key audit metrics",
        "## Operational decision outcomes",
        "## Human inspection and review volume",
        "## Human and AI evaluator agreement",
        "## Limitations and uncertainty",
        "operational audit outcomes",
        "not claims of absolute truth",
    ):
        assert required_text in report


def test_invalid_validation_result_is_rejected_without_outputs(tmp_path: Path) -> None:
    invalid = validation(record("invalid", ai_score=9))
    output_dir = tmp_path / "outputs"

    with pytest.raises(ValueError, match="valid ValidationResult"):
        generate_audit_outputs(invalid, output_dir)

    assert not output_dir.exists()


def test_rejects_output_path_outside_outputs_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="under an outputs"):
        generate_audit_outputs(validation(), tmp_path / "artifacts")
