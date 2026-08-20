"""Write reproducible REC audit tables, narrative, and static figures."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Hashable, Mapping, Sequence

from .decisions import DecisionEvaluation, evaluate_decisions
from .metrics import AuditEvaluation, AuditMetrics, evaluate_metrics
from .review_queue import ReviewQueueItem, build_review_queue
from .schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS
from .validation import ValidationResult
from .visualization import save_audit_figures


SUMMARY_FIELDS = tuple(AuditMetrics.__dataclass_fields__)
PRIORITY_FIELDS = (
    "priority_decision_tier",
    "priority_severity_rank",
    "priority_confirmed_risk_flags",
    "priority_disagreement_magnitude",
    "priority_evaluator_confidence",
    "priority_reasons",
)
COMPARISON_FIELDS = (
    "score_difference",
    "absolute_score_difference",
    "exact_agreement",
    "within_one_agreement",
)
DECISION_FIELDS = (
    "decision",
    "decision_triggers",
    "decision_reasons",
    "rule_version",
)
EVALUATED_FIELDS = (
    *REQUIRED_COLUMNS,
    *OPTIONAL_COLUMNS,
    *COMPARISON_FIELDS,
    *DECISION_FIELDS,
    *PRIORITY_FIELDS,
)


@dataclass(frozen=True)
class AuditArtifacts:
    """Paths to every artifact produced by one audit-output run."""

    output_dir: Path
    evaluated_responses: Path
    human_review_queue: Path
    overall_summary: Path
    model_summary: Path
    category_summary: Path
    error_summary: Path
    severity_summary: Path
    audit_summary: Path
    figures: tuple[Path, ...]

    @property
    def all_files(self) -> tuple[Path, ...]:
        return (
            self.evaluated_responses,
            self.human_review_queue,
            self.overall_summary,
            self.model_summary,
            self.category_summary,
            self.error_summary,
            self.severity_summary,
            self.audit_summary,
            *self.figures,
        )


def generate_audit_outputs(
    validation_result: ValidationResult,
    output_dir: str | Path = "outputs",
    run_metadata: Mapping[str, Any] | None = None,
    rules_path: str | Path | None = None,
) -> AuditArtifacts:
    """Generate all Milestone 5 artifacts from one valid dataset."""

    if not validation_result.is_valid:
        raise ValueError("Audit outputs require a valid ValidationResult with no issues.")

    destination = _prepare_output_directory(output_dir)
    audit = evaluate_metrics(validation_result)
    decisions = evaluate_decisions(validation_result, rules_path=rules_path)
    review_queue = build_review_queue(decisions)
    priority_by_response = {
        item.record["response_id"]: item for item in review_queue
    }

    paths = AuditArtifacts(
        output_dir=destination,
        evaluated_responses=destination / "evaluated_responses.csv",
        human_review_queue=destination / "human_review_queue.csv",
        overall_summary=destination / "overall_summary.csv",
        model_summary=destination / "model_summary.csv",
        category_summary=destination / "category_summary.csv",
        error_summary=destination / "error_summary.csv",
        severity_summary=destination / "severity_summary.csv",
        audit_summary=destination / "audit_summary.md",
        figures=(),
    )

    evaluated_rows = [
        _row_with_priority(row, priority_by_response.get(row["response_id"]))
        for row in decisions.rows
    ]
    _write_records_csv(
        paths.evaluated_responses,
        evaluated_rows,
        fallback_fields=EVALUATED_FIELDS,
    )
    _write_records_csv(
        paths.human_review_queue,
        [_row_with_priority(item.record, item) for item in review_queue],
        fallback_fields=EVALUATED_FIELDS,
    )
    _write_overall_summary(paths.overall_summary, audit.overall, decisions.rule_version)
    _write_group_summary(paths.model_summary, "model_name", audit.by_model, decisions.rule_version)
    _write_group_summary(
        paths.category_summary,
        "category",
        audit.by_category,
        decisions.rule_version,
    )
    _write_group_summary(
        paths.error_summary,
        "error_type",
        audit.by_error_type,
        decisions.rule_version,
    )
    _write_group_summary(
        paths.severity_summary,
        "error_severity",
        audit.by_severity,
        decisions.rule_version,
    )
    paths.audit_summary.write_text(
        _markdown_report(audit, decisions, review_queue, run_metadata or {}),
        encoding="utf-8",
    )
    figures = save_audit_figures(audit, decisions, review_queue, destination)
    return replace(paths, figures=figures)


def _prepare_output_directory(output_dir: str | Path) -> Path:
    destination = Path(output_dir)
    if "outputs" not in destination.parts:
        raise ValueError("Generated audit artifacts must be written under an outputs/ directory.")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError(f"Audit output path is not a directory: '{destination}'.")
    return destination


def _row_with_priority(
    row: Mapping[str, Any], item: ReviewQueueItem | None
) -> dict[str, Any]:
    result = dict(row)
    if item is None:
        result.update({field: None for field in PRIORITY_FIELDS})
    else:
        priority = item.priority
        result.update(
            priority_decision_tier=priority.decision_tier,
            priority_severity_rank=priority.severity_rank,
            priority_confirmed_risk_flags=priority.confirmed_risk_flags,
            priority_disagreement_magnitude=priority.disagreement_magnitude,
            priority_evaluator_confidence=priority.evaluator_confidence,
            priority_reasons=item.priority_reasons,
        )
    return result


def _write_records_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fallback_fields: Sequence[str] = (),
) -> None:
    fields = _discover_fields(rows) or tuple(fallback_fields)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _serialize(row.get(field)) for field in fields})


def _discover_fields(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    return tuple(fields)


def _serialize(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (tuple, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _write_overall_summary(path: Path, metrics: AuditMetrics, rule_version: str) -> None:
    _write_records_csv(path, [{**asdict(metrics), "rule_version": rule_version}])


def _write_group_summary(
    path: Path,
    group_field: str,
    groups: Mapping[Hashable, AuditMetrics],
    rule_version: str,
) -> None:
    rows = [
        {group_field: key, **asdict(metrics), "rule_version": rule_version}
        for key, metrics in sorted(groups.items(), key=lambda item: str(item[0] or ""))
    ]
    _write_records_csv(
        path,
        rows,
        fallback_fields=(group_field, *SUMMARY_FIELDS, "rule_version"),
    )


def _markdown_report(
    audit: AuditEvaluation,
    decisions: DecisionEvaluation,
    review_queue: Sequence[ReviewQueueItem],
    run_metadata: Mapping[str, Any],
) -> str:
    metrics = audit.overall
    decision_counts = Counter(row["decision"] for row in decisions.rows)
    fail_count = decision_counts["FAIL"]
    review_count = decision_counts["HUMAN_REVIEW"]
    metadata = {
        "Dataset": "Caller-supplied validated dataset",
        "Run identifier": "Not supplied",
        **{str(key): value for key, value in sorted(run_metadata.items())},
    }
    metadata_lines = "\n".join(
        f"- **{_markdown_text(key)}:** {_markdown_text(value)}"
        for key, value in metadata.items()
    )
    decision_lines = "\n".join(
        f"| {decision} | {decision_counts[decision]} |"
        for decision in ("PASS", "HUMAN_REVIEW", "FAIL")
    )
    return f"""# REC Audit Summary

## Technical summary

- This audit evaluated **{metrics.number_of_responses} responses** across **{metrics.number_of_prompts} prompts** using rule version **{decisions.rule_version}**.
- **{fail_count} responses received FAIL** and require mandatory human inspection and remediation. Their final decision remains FAIL.
- **{review_count} responses received HUMAN_REVIEW** because configured uncertainty or material-concern rules require human judgment.
- Exact evaluator agreement was **{_format_percent(metrics.exact_agreement_rate)}**; signed evaluator bias (`ai_score - human_score`) was **{_format_number(metrics.signed_evaluator_bias)}**.

## Dataset and run metadata

{metadata_lines}
- **Rule version:** {decisions.rule_version}
- **Prompts:** {metrics.number_of_prompts}
- **Responses:** {metrics.number_of_responses}
- **Generation time:** Not embedded; identical analytical inputs remain reproducible.

## Key audit metrics

| Metric | Value |
|---|---:|
| Average human score | {_format_number(metrics.average_human_score)} |
| Average AI score | {_format_number(metrics.average_ai_score)} |
| Exact agreement rate | {_format_percent(metrics.exact_agreement_rate)} |
| Agreement within one point | {_format_percent(metrics.agreement_within_one_point)} |
| Signed evaluator bias | {_format_number(metrics.signed_evaluator_bias)} |
| Mean absolute score difference | {_format_number(metrics.mean_absolute_score_difference)} |
| AI overrating rate | {_format_percent(metrics.ai_overrating_rate)} |
| AI underrating rate | {_format_percent(metrics.ai_underrating_rate)} |
| Critical failure count | {metrics.critical_failure_count} |
| Critical failure rate | {_format_percent(metrics.critical_failure_rate)} |

## Operational decision outcomes

| Decision | Responses |
|---|---:|
{decision_lines}

PASS, HUMAN_REVIEW, and FAIL are operational audit outcomes under the configured methodology. They are not claims of absolute truth. FAIL cases remain FAIL when queued for mandatory inspection; inspection supports auditability and remediation rather than automatic reclassification.

## Human inspection and review volume

The deterministic queue contains **{len(review_queue)} cases**: **{fail_count} FAIL cases first**, followed by **{review_count} HUMAN_REVIEW cases**. Priority is lexicographic: decision tier, severity, confirmed safety/privacy failures, disagreement magnitude, lower evaluator confidence, and original row order for stable ties.

## Human and AI evaluator agreement

The average human score was **{_format_number(metrics.average_human_score)}** and the average AI score was **{_format_number(metrics.average_ai_score)}**. Exact agreement was **{_format_percent(metrics.exact_agreement_rate)}**, while agreement within one point was **{_format_percent(metrics.agreement_within_one_point)}**. Positive signed bias means AI scores were higher on average; negative bias means they were lower.

## Methodology

Only data that passed REC validation entered the audit. Row-level score comparisons were calculated before configured decision rules were applied. Every activated decision trigger and readable reason was retained. Decision precedence was FAIL over HUMAN_REVIEW over PASS. Group summaries use the same response-level denominators as the overall metrics.

## Limitations and uncertainty

- Human judgments are a reference signal and may contain disagreement or bias.
- AI evaluator confidence may be poorly calibrated.
- Unknown safety or privacy assessments remain distinct from confirmed negatives and do not automatically trigger review in Version 1.
- Open category and error-type labels depend on consistent dataset-level annotation.
- Aggregate metrics describe this validated dataset only; they do not establish causal performance or universal model quality.

## Recommended next steps

Inspect FAIL cases for remediation first, then resolve HUMAN_REVIEW cases in queue order. Reassess configured thresholds only with documented calibration evidence and a new rule version when behavior changes.

## Further questions

- Are safety and privacy assessments complete enough for this audit's intended scope?
- Do reviewed outcomes support recalibrating evaluator confidence or disagreement thresholds?
"""


def _format_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _markdown_text(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
