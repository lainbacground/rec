"""Dataset field definitions and validation constraints for REC."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = (
    "response_id",
    "prompt_id",
    "prompt",
    "model_response",
    "model_name",
    "category",
    "human_score",
    "ai_score",
    "evaluator_confidence",
    "error_severity",
)

OPTIONAL_COLUMNS = (
    "error_type",
    "safety_failure",
    "privacy_failure",
    "human_notes",
    "review_status",
)

TEXT_REQUIRED_COLUMNS = (
    "response_id",
    "prompt_id",
    "prompt",
    "model_response",
    "model_name",
    "category",
)

SCORE_COLUMNS = ("human_score", "ai_score")
TRI_STATE_COLUMNS = ("safety_failure", "privacy_failure")
ALLOWED_REVIEW_STATUSES = frozenset({"NOT_REVIEWED", "IN_REVIEW", "RESOLVED"})


@dataclass(frozen=True)
class ValidationSchema:
    """Validation constraints sourced from the versioned REC configuration."""

    rule_version: str
    score_minimum: int
    score_maximum: int
    confidence_minimum: float
    confidence_maximum: float
    allowed_severities: frozenset[str]


def default_rules_path() -> Path:
    """Return the repository's default evaluation-rules path."""

    return Path(__file__).resolve().parents[2] / "config" / "evaluation_rules.json"


def load_validation_schema(rules_path: str | Path | None = None) -> ValidationSchema:
    """Load validation constraints from the Milestone 1 rules configuration."""

    path = Path(rules_path) if rules_path is not None else default_rules_path()
    try:
        with path.open(encoding="utf-8") as rules_file:
            rules: dict[str, Any] = json.load(rules_file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"REC rules file was not found at '{path}'. "
            "Restore config/evaluation_rules.json or provide rules_path."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"REC rules file '{path}' is not valid JSON: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})."
        ) from exc

    try:
        return ValidationSchema(
            rule_version=str(rules["rule_version"]),
            score_minimum=int(rules["score_scale"]["minimum"]),
            score_maximum=int(rules["score_scale"]["maximum"]),
            confidence_minimum=float(rules["confidence_scale"]["minimum"]),
            confidence_maximum=float(rules["confidence_scale"]["maximum"]),
            allowed_severities=frozenset(rules["allowed_severities"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"REC rules file '{path}' is missing a valid validation constraint: {exc}."
        ) from exc

