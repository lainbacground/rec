"""Apply versioned REC decision rules to validated, evaluated responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .metrics import evaluate_metrics
from .schema import default_rules_path
from .validation import ValidationResult


@dataclass(frozen=True)
class DecisionEvaluation:
    """Decision-enriched row copies and the rule version that produced them."""

    rows: tuple[Mapping[str, Any], ...]
    rule_version: str


def evaluate_decisions(
    validation_result: ValidationResult,
    rules_path: str | Path | None = None,
) -> DecisionEvaluation:
    """Assign exactly one configured decision to every valid evaluated row."""

    if not validation_result.is_valid:
        raise ValueError("Decisions require a valid ValidationResult with no issues.")

    rules = _load_rules(rules_path)
    rule_version = str(rules["rule_version"])
    if validation_result.rule_version != rule_version:
        raise ValueError(
            "Validation and decision rule versions differ; revalidate with the "
            "same rules used for decisions."
        )

    evaluated_rows = evaluate_metrics(validation_result).rows
    decided_rows = tuple(_decide_row(row, rules) for row in evaluated_rows)
    return DecisionEvaluation(rows=decided_rows, rule_version=rule_version)


def _decide_row(row: Mapping[str, Any], rules: Mapping[str, Any]) -> Mapping[str, Any]:
    activated: list[Mapping[str, Any]] = []
    for rule in (*rules["fail_rules"], *rules["human_review_rules"]):
        if _rule_matches(row, rule, rules):
            activated.append(rule)

    active_decisions = {rule["decision"] for rule in activated}
    decision = next(
        candidate
        for candidate in rules["decision_precedence"]
        if candidate in active_decisions or candidate == rules["default_decision"]
    )

    result = dict(row)
    result.update(
        decision=decision,
        decision_triggers=tuple(rule["code"] for rule in activated),
        decision_reasons=tuple(rule["reason"] for rule in activated),
        rule_version=rules["rule_version"],
    )
    return result


def _rule_matches(
    row: Mapping[str, Any], rule: Mapping[str, Any], rules: Mapping[str, Any]
) -> bool:
    actual = _rule_value(row, rule)
    expected = (
        _resolve_reference(rules, rule["threshold_reference"])
        if "threshold_reference" in rule
        else rule["value"]
    )
    operator = rule["operator"]
    if operator == "equals":
        return actual == expected
    if operator == "less_than":
        return actual < expected
    if operator == "greater_than_or_equal":
        return actual >= expected
    raise ValueError(f"Unsupported decision-rule operator: {operator!r}.")


def _rule_value(row: Mapping[str, Any], rule: Mapping[str, Any]) -> Any:
    if rule.get("calculation") == "absolute_difference":
        fields = rule["fields"]
        derived_difference = row.get("absolute_score_difference")
        if derived_difference is not None:
            return derived_difference
        return abs(row[fields[0]] - row[fields[1]])
    return row.get(rule["field"])


def _resolve_reference(rules: Mapping[str, Any], reference: str) -> Any:
    value: Any = rules
    for part in reference.split("."):
        value = value[part]
    return value


def _load_rules(rules_path: str | Path | None) -> Mapping[str, Any]:
    path = Path(rules_path) if rules_path is not None else default_rules_path()
    try:
        with path.open(encoding="utf-8") as rules_file:
            rules = json.load(rules_file)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load decision rules from '{path}': {exc}.") from exc

    required = {
        "rule_version",
        "decision_precedence",
        "fail_rules",
        "human_review_rules",
        "default_decision",
    }
    if not isinstance(rules, dict) or not required.issubset(rules):
        raise ValueError(f"Decision rules file '{path}' is missing required sections.")
    return rules
