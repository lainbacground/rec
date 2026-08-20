from __future__ import annotations

from copy import deepcopy

import pytest

from rec.data_loader import dataset_from_records, load_csv
from rec.schema import REQUIRED_COLUMNS
from rec.validation import validate_dataset


def valid_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "response_id": "response-001",
        "prompt_id": "prompt-001",
        "prompt": "Give a concise factual answer.",
        "model_response": "A concise answer.",
        "model_name": "example-model",
        "category": "illustrative",
        "human_score": 4,
        "ai_score": 4,
        "evaluator_confidence": 0.85,
        "error_severity": "none",
        "error_type": None,
        "safety_failure": None,
        "privacy_failure": False,
        "human_notes": None,
        "review_status": None,
    }
    record.update(overrides)
    return record


def validate_records(*records: dict[str, object]):
    columns = tuple(valid_record().keys())
    return validate_dataset(dataset_from_records(records, columns=columns))


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_valid_record_is_normalized_on_a_copy() -> None:
    original = valid_record(
        response_id=" response-001 ",
        human_score="4",
        ai_score="5",
        evaluator_confidence="0.85",
        error_severity=" LOW ",
        safety_failure="",
        privacy_failure="false",
    )
    snapshot = deepcopy(original)

    result = validate_records(original)

    assert result.is_valid
    assert original == snapshot
    normalized = result.normalized_rows[0]
    assert normalized["response_id"] == "response-001"
    assert normalized["human_score"] == 4
    assert normalized["evaluator_confidence"] == 0.85
    assert normalized["error_severity"] == "low"
    assert normalized["safety_failure"] is None
    assert normalized["privacy_failure"] is False


def test_reports_each_missing_required_column() -> None:
    columns = [column for column in REQUIRED_COLUMNS if column != "human_score"]
    dataset = dataset_from_records([valid_record()], columns=columns)

    result = validate_dataset(dataset)

    assert any(
        issue.code == "MISSING_COLUMN" and issue.field == "human_score"
        for issue in result.issues
    )


def test_rejects_duplicate_response_ids_after_safe_normalization() -> None:
    result = validate_records(
        valid_record(response_id="response-001"),
        valid_record(response_id=" response-001 ", prompt_id="prompt-002"),
    )

    duplicate = [
        issue for issue in result.issues if issue.code == "DUPLICATE_RESPONSE_ID"
    ]
    assert len(duplicate) == 1
    assert "duplicates row 2" in duplicate[0].message


@pytest.mark.parametrize("field", ["human_score", "ai_score"])
@pytest.mark.parametrize("value", [0, 6])
def test_rejects_scores_outside_documented_range(field: str, value: int) -> None:
    result = validate_records(valid_record(**{field: value}))

    assert "SCORE_OUT_OF_RANGE" in issue_codes(result)


@pytest.mark.parametrize("value", ["3.5", True, "high"])
def test_rejects_non_integer_scores(value: object) -> None:
    result = validate_records(valid_record(human_score=value))

    assert "INVALID_INTEGER" in issue_codes(result)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_rejects_confidence_outside_documented_range(value: float) -> None:
    result = validate_records(valid_record(evaluator_confidence=value))

    assert "CONFIDENCE_OUT_OF_RANGE" in issue_codes(result)


@pytest.mark.parametrize("value", ["confident", True, float("nan")])
def test_rejects_invalid_confidence_types_or_values(value: object) -> None:
    result = validate_records(valid_record(evaluator_confidence=value))

    assert "INVALID_FLOAT" in issue_codes(result)


def test_rejects_unknown_severity() -> None:
    result = validate_records(valid_record(error_severity="urgent"))

    assert "INVALID_SEVERITY" in issue_codes(result)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), (None, None), ("true", True), ("false", False), ("", None)],
)
def test_preserves_tri_state_meaning(value: object, expected: bool | None) -> None:
    result = validate_records(valid_record(safety_failure=value))

    assert result.is_valid
    assert result.normalized_rows[0]["safety_failure"] is expected


@pytest.mark.parametrize("value", [0, 1, "unknown", "yes", "no"])
def test_rejects_invalid_tri_state_values(value: object) -> None:
    result = validate_records(valid_record(privacy_failure=value))

    assert "INVALID_TRI_STATE" in issue_codes(result)


@pytest.mark.parametrize(
    "field",
    [
        "response_id",
        "prompt_id",
        "prompt",
        "model_response",
        "model_name",
        "category",
        "error_severity",
    ],
)
def test_rejects_empty_required_text(field: str) -> None:
    result = validate_records(valid_record(**{field: "  "}))

    assert any(
        issue.code == "MISSING_REQUIRED_VALUE" and issue.field == field
        for issue in result.issues
    )


@pytest.mark.parametrize("field", ["human_score", "ai_score", "evaluator_confidence"])
@pytest.mark.parametrize("value", [None, "  "])
def test_rejects_missing_required_values(field: str, value: object) -> None:
    result = validate_records(valid_record(**{field: value}))

    assert any(
        issue.code == "MISSING_REQUIRED_VALUE" and issue.field == field
        for issue in result.issues
    )


@pytest.mark.parametrize("field", ["prompt", "error_severity"])
def test_null_required_text_is_reported_as_missing(field: str) -> None:
    result = validate_records(valid_record(**{field: None}))

    assert any(
        issue.code == "MISSING_REQUIRED_VALUE" and issue.field == field
        for issue in result.issues
    )


def test_rejects_wrong_basic_types_with_readable_location() -> None:
    result = validate_records(valid_record(prompt=123))

    issue = next(issue for issue in result.issues if issue.field == "prompt")
    assert issue.code == "INVALID_TYPE"
    assert "row 2, field 'prompt'" in str(issue)
    assert "Expected text" in str(issue)


def test_load_csv_does_not_modify_raw_file(tmp_path) -> None:
    raw_file = tmp_path / "tiny.csv"
    original = (
        ",".join(REQUIRED_COLUMNS)
        + "\nresponse-001,prompt-001,Prompt,Response,model,category,4,4,0.9,none\n"
    )
    raw_file.write_text(original, encoding="utf-8")

    dataset = load_csv(raw_file)
    result = validate_dataset(dataset)

    assert result.is_valid
    assert raw_file.read_text(encoding="utf-8") == original


def test_missing_csv_has_actionable_error(tmp_path) -> None:
    missing = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError, match="Check the path"):
        load_csv(missing)
