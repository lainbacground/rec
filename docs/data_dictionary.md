# REC Data Dictionary

## Purpose

REC accepts one row per evaluated model response. The input contains the original prompt and response, identifying metadata, and the human and AI evaluator annotations needed for an audit. REC will validate these fields before calculating any derived values.

The initial interchange format is UTF-8 CSV with a header row. Column names use `snake_case`. Empty strings are treated as missing values, not as zero or `false`.

## Field groups

### Required input fields

These fields must be present and non-empty in every valid input row.

| Field | Type | Allowed values or format | Description |
|---|---|---|---|
| `response_id` | string | Unique, non-empty | Stable identifier for one evaluated response. |
| `prompt_id` | string | Non-empty | Identifier shared by responses to the same prompt. |
| `prompt` | string | Non-empty text | Prompt or task presented to the model. |
| `model_response` | string | Non-empty text | Model output being evaluated. |
| `model_name` | string | Non-empty | Model identifier or comparison label. |
| `category` | string | Non-empty | Extensible task grouping. REC does not impose a fixed category list. |
| `human_score` | integer | `1` through `5` | Human evaluator's overall quality score under the REC rubric. |
| `ai_score` | integer | `1` through `5` | AI evaluator's overall quality score under the same rubric. |
| `evaluator_confidence` | float | `0.0` through `1.0`, inclusive | AI evaluator's confidence in its judgment. |
| `error_severity` | string | `none`, `low`, `medium`, `high`, `critical` | Highest confirmed error severity for the response. |

Identifiers are strings even when they contain only digits. This preserves leading zeroes and permits identifiers such as `prompt-001`.

### Optional evaluation and human annotations

These fields may be absent or empty. Their absence must not silently be interpreted as a confirmed negative finding.

| Field | Type | Allowed values or format | Description |
|---|---|---|---|
| `error_type` | string | Extensible taxonomy label | Primary error type, when an error is identified. Values are not restricted to the prototype taxonomy. Multiple errors may use a documented delimiter in a later schema revision; Version 1 treats this as one primary label. |
| `safety_failure` | boolean or empty | `true`, `false`, or empty | Safety assessment result. `true` means an assessed, confirmed failure; `false` means the dimension was assessed and no failure was found; empty/null means not assessed or unknown. |
| `privacy_failure` | boolean or empty | `true`, `false`, or empty | Privacy assessment result. `true` means an assessed, confirmed failure; `false` means the dimension was assessed and no failure was found; empty/null means not assessed or unknown. |
| `human_notes` | string | Free text | Human evaluator's supporting rationale or context. |
| `review_status` | string | `NOT_REVIEWED`, `IN_REVIEW`, `RESOLVED`, or empty | Optional workflow annotation imported from an existing review process. It does not determine REC's decision. |

Boolean CSV values should be written as lowercase `true` or `false`. The validation milestone will define whether harmless case variations can be normalized.

For both risk flags, empty/null and `false` have different meanings and must remain distinguishable. REC must never convert an empty/null safety or privacy value to `false`: unknown means no assessment result is available, while `false` records an explicit assessment with no failure found. Unknown values do not automatically trigger `HUMAN_REVIEW` in Version 1, but a future dataset profile may configure complete assessment as a requirement.

### Derived fields

These fields are not required in raw input. REC will calculate them in later milestones. If an input file contains columns with these names, the pipeline should reject them or explicitly overwrite them only in a separately generated output; it must never trust precomputed values as audit results.

| Field | Type | Description |
|---|---|---|
| `score_difference` | integer | Signed difference: `ai_score - human_score`. |
| `absolute_score_difference` | integer | Absolute distance between AI and human scores. |
| `exact_agreement` | boolean | Whether the two scores are identical. |
| `within_one_agreement` | boolean | Whether the scores differ by at most one point. |
| `decision` | string | One of `PASS`, `HUMAN_REVIEW`, or `FAIL`. |
| `decision_triggers` | list of strings | All explicit rule codes activated for the row. |
| `decision_reasons` | list of strings | Human-readable explanations corresponding to the activated rules. |
| `rule_version` | string | Version of the rules used for the decision. |
| `review_priority` | number or category | Later-derived ordering value for cases requiring review. Its method must be documented before implementation. |

Serialization of list-valued fields in CSV will be defined before the export milestone. Internally, trigger codes and explanations should remain separate values rather than an ambiguous prose string.

REC retains all activated trigger codes and their reasons for each record, regardless of decision precedence. For example, a record with critical severity, low evaluator confidence, and substantial score disagreement receives `FAIL`, but all three triggers remain visible in `decision_triggers` and `decision_reasons`.

## Consistency rules

- `response_id` must be unique across the dataset.
- Multiple responses may share a `prompt_id`.
- `error_severity = none` should normally have an empty `error_type`. A populated error type with `none` severity is inconsistent and requires correction.
- `error_severity = critical` is a confirmed critical failure and activates a `FAIL` rule.
- A confirmed safety or privacy failure activates a `FAIL` rule, regardless of score.
- `review_status` describes workflow state only; it cannot override calculated risk rules.
- Invalid required data is a validation error, not an operational `FAIL` decision. REC must not claim to have audited a row it could not evaluate reliably.

## Schema evolution

The schema intentionally leaves `category` and `error_type` open so new task groups and error taxonomies do not require code changes. Controlled vocabularies may later be supplied as project-specific configuration. Any incompatible field or meaning change should be documented and versioned rather than silently applied.
