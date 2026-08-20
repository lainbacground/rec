"""Validate and safely normalize REC input records in memory."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .data_loader import LoadedDataset
from .schema import (
    ALLOWED_REVIEW_STATUSES,
    REQUIRED_COLUMNS,
    SCORE_COLUMNS,
    TEXT_REQUIRED_COLUMNS,
    TRI_STATE_COLUMNS,
    ValidationSchema,
    load_validation_schema,
)


@dataclass(frozen=True)
class ValidationIssue:
    """One actionable problem found in an input dataset."""

    code: str
    message: str
    field: str | None = None
    row_number: int | None = None

    def __str__(self) -> str:
        location: list[str] = []
        if self.row_number is not None:
            location.append(f"row {self.row_number}")
        if self.field is not None:
            location.append(f"field '{self.field}'")
        prefix = f"{', '.join(location)}: " if location else ""
        return f"{prefix}{self.message}"


@dataclass(frozen=True)
class ValidationResult:
    """Validation issues and a normalized copy of the supplied rows."""

    normalized_rows: tuple[Mapping[str, Any], ...]
    issues: tuple[ValidationIssue, ...]
    rule_version: str

    @property
    def is_valid(self) -> bool:
        return not self.issues


def validate_dataset(
    dataset: LoadedDataset, schema: ValidationSchema | None = None
) -> ValidationResult:
    """Validate a dataset and normalize safe values on copied rows only."""

    active_schema = schema or load_validation_schema()
    issues: list[ValidationIssue] = []
    normalized_rows: list[dict[str, Any]] = []

    duplicate_headers = sorted(
        {column for column in dataset.columns if dataset.columns.count(column) > 1}
    )
    for column in duplicate_headers:
        issues.append(
            ValidationIssue(
                code="DUPLICATE_COLUMN",
                field=column,
                message="The CSV header contains this column more than once; keep only one.",
            )
        )

    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in dataset.columns
    ]
    for column in missing_columns:
        issues.append(
            ValidationIssue(
                code="MISSING_COLUMN",
                field=column,
                message="Required column is missing; add it to the input header.",
            )
        )

    seen_response_ids: dict[str, int] = {}
    for index, source_row in enumerate(dataset.rows, start=2):
        row = dict(source_row)

        for field in TEXT_REQUIRED_COLUMNS:
            if field not in dataset.columns:
                continue
            value = row.get(field)
            if _is_missing(value):
                issues.append(_missing_value_issue(index, field))
            elif not isinstance(value, str):
                issues.append(_type_issue(index, field, "text", value))
            elif field in {"response_id", "prompt_id", "model_name", "category"}:
                row[field] = value.strip()

        for field in SCORE_COLUMNS:
            if field not in dataset.columns:
                continue
            score_value = row.get(field)
            parsed_score = _parse_integer(score_value)
            if _is_missing(score_value):
                issues.append(_missing_value_issue(index, field))
            elif parsed_score is None:
                issues.append(
                    ValidationIssue(
                        code="INVALID_INTEGER",
                        row_number=index,
                        field=field,
                        message=(
                            f"Expected a whole-number score from "
                            f"{active_schema.score_minimum} to {active_schema.score_maximum}; "
                            f"received {row.get(field)!r}."
                        ),
                    )
                )
            elif not active_schema.score_minimum <= parsed_score <= active_schema.score_maximum:
                issues.append(
                    ValidationIssue(
                        code="SCORE_OUT_OF_RANGE",
                        row_number=index,
                        field=field,
                        message=(
                            f"Score must be between {active_schema.score_minimum} and "
                            f"{active_schema.score_maximum}; received {parsed_score}."
                        ),
                    )
                )
            else:
                row[field] = parsed_score

        confidence_field = "evaluator_confidence"
        if confidence_field in dataset.columns:
            confidence_value = row.get(confidence_field)
            confidence = _parse_float(confidence_value)
            if _is_missing(confidence_value):
                issues.append(_missing_value_issue(index, confidence_field))
            elif confidence is None:
                issues.append(
                    ValidationIssue(
                        code="INVALID_FLOAT",
                        row_number=index,
                        field=confidence_field,
                        message=(
                            "Expected a numeric confidence value from "
                            f"{active_schema.confidence_minimum} to "
                            f"{active_schema.confidence_maximum}; received "
                            f"{row.get(confidence_field)!r}."
                        ),
                    )
                )
            elif not (
                active_schema.confidence_minimum
                <= confidence
                <= active_schema.confidence_maximum
            ):
                issues.append(
                    ValidationIssue(
                        code="CONFIDENCE_OUT_OF_RANGE",
                        row_number=index,
                        field=confidence_field,
                        message=(
                            f"Confidence must be between {active_schema.confidence_minimum} "
                            f"and {active_schema.confidence_maximum}; received {confidence}."
                        ),
                    )
                )
            else:
                row[confidence_field] = confidence

        severity_field = "error_severity"
        if severity_field in dataset.columns:
            severity = row.get(severity_field)
            if _is_missing(severity):
                issues.append(_missing_value_issue(index, severity_field))
            elif not isinstance(severity, str):
                issues.append(_type_issue(index, severity_field, "text", severity))
            else:
                normalized_severity = severity.strip().lower()
                if normalized_severity not in active_schema.allowed_severities:
                    allowed = ", ".join(sorted(active_schema.allowed_severities))
                    issues.append(
                        ValidationIssue(
                            code="INVALID_SEVERITY",
                            row_number=index,
                            field=severity_field,
                            message=(
                                f"Severity must be one of: {allowed}; received {severity!r}."
                            ),
                        )
                    )
                else:
                    row[severity_field] = normalized_severity

        for field in TRI_STATE_COLUMNS:
            if field not in dataset.columns:
                continue
            valid, normalized_value = _parse_tri_state(row.get(field))
            if not valid:
                issues.append(
                    ValidationIssue(
                        code="INVALID_TRI_STATE",
                        row_number=index,
                        field=field,
                        message=(
                            "Expected true, false, or an empty value for unknown/not assessed; "
                            f"received {row.get(field)!r}."
                        ),
                    )
                )
            else:
                row[field] = normalized_value

        _normalize_optional_text(row, dataset.columns, issues, index)

        response_id = row.get("response_id")
        if isinstance(response_id, str) and response_id:
            if response_id in seen_response_ids:
                first_row = seen_response_ids[response_id]
                issues.append(
                    ValidationIssue(
                        code="DUPLICATE_RESPONSE_ID",
                        row_number=index,
                        field="response_id",
                        message=(
                            f"Response ID {response_id!r} duplicates row {first_row}; "
                            "assign a unique response_id."
                        ),
                    )
                )
            else:
                seen_response_ids[response_id] = index

        normalized_rows.append(row)

    return ValidationResult(
        normalized_rows=tuple(normalized_rows),
        issues=tuple(issues),
        rule_version=active_schema.rule_version,
    )


def _parse_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("+-").isdigit():
            return int(stripped)
    return None


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_tri_state(value: Any) -> tuple[bool, bool | None]:
    if value is None:
        return True, None
    if isinstance(value, bool):
        return True, value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return True, None
        if normalized == "true":
            return True, True
        if normalized == "false":
            return True, False
    return False, None


def _normalize_optional_text(
    row: dict[str, Any],
    columns: tuple[str, ...],
    issues: list[ValidationIssue],
    row_number: int,
) -> None:
    for field in ("error_type", "human_notes", "review_status"):
        if field not in columns:
            continue
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            row[field] = None
            continue
        if not isinstance(value, str):
            issues.append(_type_issue(row_number, field, "text or empty", value))
            continue

        normalized = value.strip()
        if field == "review_status":
            normalized = normalized.upper()
            if normalized not in ALLOWED_REVIEW_STATUSES:
                allowed = ", ".join(sorted(ALLOWED_REVIEW_STATUSES))
                issues.append(
                    ValidationIssue(
                        code="INVALID_REVIEW_STATUS",
                        row_number=row_number,
                        field=field,
                        message=(
                            f"Review status must be one of: {allowed}, or empty; "
                            f"received {value!r}."
                        ),
                    )
                )
        row[field] = normalized


def _missing_value_issue(row_number: int, field: str) -> ValidationIssue:
    return ValidationIssue(
        code="MISSING_REQUIRED_VALUE",
        row_number=row_number,
        field=field,
        message="Required value is empty; provide a value before running the audit.",
    )


def _type_issue(
    row_number: int, field: str, expected: str, value: Any
) -> ValidationIssue:
    return ValidationIssue(
        code="INVALID_TYPE",
        row_number=row_number,
        field=field,
        message=f"Expected {expected}; received {type(value).__name__} value {value!r}.",
    )
