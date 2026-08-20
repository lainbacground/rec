from __future__ import annotations

from pathlib import Path

import pytest
from matplotlib import image as mpimg

from rec.data_loader import dataset_from_records
from rec.decisions import evaluate_decisions
from rec.metrics import evaluate_metrics
from rec.review_queue import build_review_queue
from rec.validation import validate_dataset
from rec.visualization import FIGURE_FILENAMES, save_audit_figures


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


def test_generates_readable_nonempty_png_files(tmp_path: Path) -> None:
    rows = [
        record("pass"),
        record("review", model_name="model-b", error_severity="high"),
        record("fail", model_name="model-b", safety_failure=True),
    ]
    valid = validate_dataset(dataset_from_records(rows))
    audit = evaluate_metrics(valid)
    decisions = evaluate_decisions(valid)
    queue = build_review_queue(decisions)
    output_dir = tmp_path / "outputs"

    paths = save_audit_figures(audit, decisions, queue, output_dir)

    assert tuple(path.name for path in paths) == FIGURE_FILENAMES
    for path in paths:
        assert path.stat().st_size > 1_000
        image = mpimg.imread(path)
        assert image.size > 0
        assert image.shape[0] > 100
        assert image.shape[1] > 100


def test_rejects_figure_path_outside_outputs_directory(tmp_path: Path) -> None:
    valid = validate_dataset(dataset_from_records([record("pass")]))
    audit = evaluate_metrics(valid)
    decisions = evaluate_decisions(valid)

    with pytest.raises(ValueError, match="under an outputs"):
        save_audit_figures(audit, decisions, (), tmp_path / "figures")
