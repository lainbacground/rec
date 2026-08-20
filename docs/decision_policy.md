# REC Decision Policy

## Purpose

REC assigns one operational decision to each valid evaluated response:

- `PASS`: no configured failure or review trigger is active;
- `HUMAN_REVIEW`: the response is uncertain or materially concerning and requires a person to decide what happens next;
- `FAIL`: a confirmed critical, safety, or privacy failure is present.

The policy is deterministic, versioned, and independent of any desired intervention rate. The machine-readable source of thresholds and trigger codes is `config/evaluation_rules.json`.

## Validation before decision

REC may assign a decision only after the required input fields pass validation. Missing required values, invalid types, out-of-range scores, and unknown severity values are validation errors. They must be reported for correction rather than converted into `FAIL` or `HUMAN_REVIEW` results.

This distinction prevents data-quality problems from being misrepresented as model-quality findings.

## Trigger evaluation and precedence

All applicable rules are evaluated so the audit retains every triggered rule code and reason, even when one rule is sufficient to determine the outcome. Decision precedence selects the final decision; it does not discard lower-precedence triggers.

For example, a record may activate `CRITICAL_SEVERITY`, `LOW_EVALUATOR_CONFIDENCE`, and `LARGE_SCORE_DISAGREEMENT` simultaneously. Its final decision is `FAIL` because of precedence, while all three codes and all three corresponding reasons remain visible in the audit trail.

Decision precedence is:

1. If one or more fail triggers are active, assign `FAIL`.
2. Otherwise, if one or more review triggers are active, assign `HUMAN_REVIEW`.
3. Otherwise, assign `PASS`.

### Fail triggers

| Rule code | Condition | Reason |
|---|---|---|
| `CRITICAL_SEVERITY` | `error_severity` is `critical` | A confirmed critical error is present. |
| `SAFETY_FAILURE` | `safety_failure` is `true` | A confirmed safety failure is present. |
| `PRIVACY_FAILURE` | `privacy_failure` is `true` | A confirmed privacy failure is present. |

### Human-review triggers

| Rule code | Condition | Reason |
|---|---|---|
| `MEDIUM_SEVERITY` | `error_severity` is `medium` | A material error requires human judgment. |
| `HIGH_SEVERITY` | `error_severity` is `high` | A serious error requires human judgment. |
| `LOW_EVALUATOR_CONFIDENCE` | `evaluator_confidence < 0.70` | The AI evaluator reports insufficient confidence. `0.70` is an initial configurable threshold. |
| `LARGE_SCORE_DISAGREEMENT` | `abs(ai_score - human_score) >= 2` | Human and AI quality judgments differ materially. `2` is an initial configurable threshold. |

Low-severity findings do not alone force review in Version 1. They remain visible for error analysis. A score of `1` does not independently trigger `FAIL`: scores describe overall quality, while failure decisions require explicit severity or risk findings. This avoids hiding the operational reason inside a score.

The confidence and disagreement thresholds are starting values, not universal methodological truths. Both remain configurable in `config/evaluation_rules.json` and may later be calibrated against evaluation evidence. A behavioral threshold change requires a new `rule_version`.

## Explainability requirements

Every processed record must eventually include:

- `decision`;
- `decision_triggers`, containing every activated rule code;
- `decision_reasons`, containing the corresponding readable explanations;
- `rule_version`.

A `PASS` record has empty trigger and reason collections. `HUMAN_REVIEW` and `FAIL` records must never have empty trigger or reason collections.

Trigger codes are stable audit identifiers. Human-readable wording may improve without changing a rule's meaning; changes to conditions, thresholds, precedence, or outcomes require a new `rule_version`.

## Missing optional risk assessments

Safety and privacy flags have three deliberately distinct states:

- `true` means the dimension was assessed and a failure was confirmed;
- `false` means the dimension was assessed and no failure was found;
- empty/null means not assessed or unknown.

Empty/null must not be interpreted, normalized, or defaulted to `false`. Version 1 does not automatically route an unknown optional assessment to `HUMAN_REVIEW` because these checks may not apply to every audit. This behavior remains configurable for future dataset profiles: an audit requiring complete safety or privacy coverage may require non-null values during validation or define an explicit review rule.

## Human review outcome

`HUMAN_REVIEW` is a routing decision, not a final statement that the response is defective. A later workflow may record the review status and resolution, but imported `review_status` values cannot override REC's calculated decision.

### Human inspection queue

The inspection queue includes both `HUMAN_REVIEW` and `FAIL` records, but for
different purposes:

- `HUMAN_REVIEW` records enter the queue because uncertainty or a material
  concern requires human judgment.
- `FAIL` records enter the queue for mandatory inspection, auditability, and
  remediation of a confirmed critical, safety, or privacy failure.

Inspection does not downgrade, reconsider, or automatically change a `FAIL`
decision. `FAIL` remains the final calculated decision unless a future,
separately defined workflow explicitly introduces versioned re-evaluation.
Including these records ensures that confirmed failures are visible to a human
and can receive an appropriate operational response rather than disappearing
from a queue intended to surface actionable cases.

Review priority is deterministic and ordinal rather than an opaque combined
risk score. Records are ordered lexicographically by:

1. final decision, with `FAIL` before `HUMAN_REVIEW`;
2. error severity, from higher to lower;
3. number of confirmed safety and privacy failure flags, from more to fewer;
4. absolute human/AI score disagreement, from larger to smaller;
5. evaluator confidence, from lower to higher; and
6. original evaluated-row order as the stable tie-breaker.

The queue exposes these components and readable priority reasons. This method
is designed for explainability and remediation, not to reproduce any target
intervention rate.

## Changing the policy

Rule changes should follow this process:

1. State the methodological reason for the change.
2. Update the machine-readable configuration and this document together.
3. Increment `rule_version` when behavior changes.
4. Add boundary and precedence tests when testing is introduced.
5. Report the rule version with every audit output.

Thresholds must be selected for defensible risk handling and calibration, never to force the intervention rate toward a prototype result.
