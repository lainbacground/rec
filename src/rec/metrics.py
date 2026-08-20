"""Calculate evaluator-comparison metrics from validated REC data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterable, Mapping, Sequence

from .validation import ValidationResult


@dataclass(frozen=True)
class AuditMetrics:
    """Aggregate evaluator-comparison metrics for a set of response rows."""

    number_of_prompts: int
    number_of_responses: int
    average_human_score: float | None
    average_ai_score: float | None
    exact_agreement_rate: float | None
    agreement_within_one_point: float | None
    signed_evaluator_bias: float | None
    mean_absolute_score_difference: float | None
    ai_overrating_rate: float | None
    ai_underrating_rate: float | None
    critical_failure_count: int
    critical_failure_rate: float | None


@dataclass(frozen=True)
class AuditEvaluation:
    """Row comparisons, overall metrics, and requested grouped summaries."""

    rows: tuple[Mapping[str, Any], ...]
    overall: AuditMetrics
    by_model: Mapping[str, AuditMetrics]
    by_category: Mapping[str, AuditMetrics]
    by_error_type: Mapping[str | None, AuditMetrics]
    by_severity: Mapping[str, AuditMetrics]


def evaluate_metrics(validation_result: ValidationResult) -> AuditEvaluation:
    """Calculate audit metrics, refusing data that did not pass validation."""

    if not validation_result.is_valid:
        raise ValueError("Audit metrics require a valid ValidationResult with no issues.")

    rows = _add_comparison_fields(validation_result.normalized_rows)
    return AuditEvaluation(
        rows=rows,
        overall=_calculate_metrics(rows),
        by_model=_summarize_by(rows, "model_name"),
        by_category=_summarize_by(rows, "category"),
        by_error_type=_summarize_by(rows, "error_type"),
        by_severity=_summarize_by(rows, "error_severity"),
    )


def _add_comparison_fields(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Return row copies with evaluator-comparison fields calculated afresh."""

    compared_rows: list[Mapping[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        difference = row["ai_score"] - row["human_score"]
        row.update(
            score_difference=difference,
            absolute_score_difference=abs(difference),
            exact_agreement=difference == 0,
            within_one_agreement=abs(difference) <= 1,
        )
        compared_rows.append(row)
    return tuple(compared_rows)


def _calculate_metrics(rows: Sequence[Mapping[str, Any]]) -> AuditMetrics:
    """Calculate all required metrics for one possibly empty set of rows."""

    response_count = len(rows)
    if response_count == 0:
        return AuditMetrics(
            number_of_prompts=0,
            number_of_responses=0,
            average_human_score=None,
            average_ai_score=None,
            exact_agreement_rate=None,
            agreement_within_one_point=None,
            signed_evaluator_bias=None,
            mean_absolute_score_difference=None,
            ai_overrating_rate=None,
            ai_underrating_rate=None,
            critical_failure_count=0,
            critical_failure_rate=None,
        )

    critical_count = sum(row["error_severity"] == "critical" for row in rows)
    return AuditMetrics(
        number_of_prompts=len({row["prompt_id"] for row in rows}),
        number_of_responses=response_count,
        average_human_score=_mean(row["human_score"] for row in rows),
        average_ai_score=_mean(row["ai_score"] for row in rows),
        exact_agreement_rate=_rate(row["exact_agreement"] for row in rows),
        agreement_within_one_point=_rate(
            row["within_one_agreement"] for row in rows
        ),
        signed_evaluator_bias=_mean(row["score_difference"] for row in rows),
        mean_absolute_score_difference=_mean(
            row["absolute_score_difference"] for row in rows
        ),
        ai_overrating_rate=_rate(row["score_difference"] > 0 for row in rows),
        ai_underrating_rate=_rate(row["score_difference"] < 0 for row in rows),
        critical_failure_count=critical_count,
        critical_failure_rate=critical_count / response_count,
    )


def _summarize_by(
    rows: Sequence[Mapping[str, Any]], field: str
) -> dict[Hashable, AuditMetrics]:
    """Group rows by a field and calculate the same metrics for each group."""

    groups: dict[Hashable, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get(field), []).append(row)
    return {
        key: _calculate_metrics(group_rows) for key, group_rows in groups.items()
    }


def _mean(values: Iterable[float]) -> float:
    collected = tuple(values)
    return sum(collected) / len(collected)


def _rate(matches: Iterable[bool]) -> float:
    collected = tuple(matches)
    return sum(collected) / len(collected)
