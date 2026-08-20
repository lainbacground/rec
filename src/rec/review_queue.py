"""Build a deterministic, explainable human-inspection queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .decisions import DecisionEvaluation


SEVERITY_RANKS = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class ReviewPriority:
    """Visible ordinal components used to order one review item."""

    decision_tier: int
    severity_rank: int
    confirmed_risk_flags: int
    disagreement_magnitude: int
    evaluator_confidence: float


@dataclass(frozen=True)
class ReviewQueueItem:
    """One immutable queue entry with its source-order tie breaker."""

    record: Mapping[str, Any]
    priority: ReviewPriority
    priority_reasons: tuple[str, ...]
    source_index: int


def build_review_queue(decisions: DecisionEvaluation) -> tuple[ReviewQueueItem, ...]:
    """Include review and fail cases, sorting fail cases first for inspection."""

    items = [
        _queue_item(row, index)
        for index, row in enumerate(decisions.rows)
        if row["decision"] in {"FAIL", "HUMAN_REVIEW"}
    ]
    return tuple(sorted(items, key=_sort_key))


def _queue_item(row: Mapping[str, Any], source_index: int) -> ReviewQueueItem:
    record = dict(row)
    risk_flags = sum(
        record.get(field) is True for field in ("safety_failure", "privacy_failure")
    )
    priority = ReviewPriority(
        decision_tier=2 if record["decision"] == "FAIL" else 1,
        severity_rank=SEVERITY_RANKS[record["error_severity"]],
        confirmed_risk_flags=risk_flags,
        disagreement_magnitude=record["absolute_score_difference"],
        evaluator_confidence=record["evaluator_confidence"],
    )
    return ReviewQueueItem(
        record=record,
        priority=priority,
        priority_reasons=_priority_reasons(record, priority),
        source_index=source_index,
    )


def _priority_reasons(
    row: Mapping[str, Any], priority: ReviewPriority
) -> tuple[str, ...]:
    reasons = [
        (
            "FAIL requires mandatory human inspection before HUMAN_REVIEW cases."
            if row["decision"] == "FAIL"
            else "The configured rules require human review."
        )
    ]
    if priority.severity_rank:
        reasons.append(f"Error severity is {row['error_severity']}.")
    if row.get("safety_failure") is True:
        reasons.append("A safety failure is confirmed.")
    if row.get("privacy_failure") is True:
        reasons.append("A privacy failure is confirmed.")
    if priority.disagreement_magnitude:
        reasons.append(
            "Human and AI scores differ by "
            f"{priority.disagreement_magnitude} point(s)."
        )
    if "LOW_EVALUATOR_CONFIDENCE" in row["decision_triggers"]:
        reasons.append(
            f"Evaluator confidence is low at {priority.evaluator_confidence:.3g}."
        )
    return tuple(reasons)


def _sort_key(item: ReviewQueueItem) -> tuple[float, ...]:
    priority = item.priority
    return (
        -priority.decision_tier,
        -priority.severity_rank,
        -priority.confirmed_risk_flags,
        -priority.disagreement_magnitude,
        priority.evaluator_confidence,
        item.source_index,
    )
