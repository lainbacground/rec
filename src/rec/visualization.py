"""Create deterministic static visual evidence for REC audit outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .decisions import DecisionEvaluation
from .metrics import AuditEvaluation
from .review_queue import ReviewQueueItem


FIGURE_FILENAMES = (
    "evaluator_agreement.png",
    "decision_distribution_by_model.png",
    "inspection_queue_by_severity.png",
)

DECISION_ORDER = ("FAIL", "HUMAN_REVIEW", "PASS")
DECISION_COLORS = {
    "FAIL": "#b45309",
    "HUMAN_REVIEW": "#d4a72c",
    "PASS": "#3568a8",
}
SEVERITY_ORDER = ("critical", "high", "medium", "low", "none")


def save_audit_figures(
    audit: AuditEvaluation,
    decisions: DecisionEvaluation,
    review_queue: Sequence[ReviewQueueItem],
    output_dir: str | Path,
) -> tuple[Path, ...]:
    """Save the three audit figures and return their deterministic paths."""

    destination = Path(output_dir)
    if "outputs" not in destination.parts:
        raise ValueError("Audit figures must be written under an outputs/ directory.")
    destination.mkdir(parents=True, exist_ok=True)
    paths = tuple(destination / name for name in FIGURE_FILENAMES)
    _plot_evaluator_agreement(audit.rows, paths[0])
    _plot_decisions_by_model(decisions.rows, paths[1])
    _plot_queue_by_severity(review_queue, paths[2])
    return paths


def _plot_evaluator_agreement(
    rows: Sequence[Mapping[str, Any]], output_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    if not rows:
        _show_empty(ax, "No evaluated responses")
    else:
        minimum = min(min(row["human_score"], row["ai_score"]) for row in rows)
        maximum = max(max(row["human_score"], row["ai_score"]) for row in rows)
        score_minimum = min(1, minimum)
        score_maximum = max(5, maximum)
        size = score_maximum - score_minimum + 1
        counts = [[0 for _ in range(size)] for _ in range(size)]
        for row in rows:
            human_index = row["human_score"] - score_minimum
            ai_index = row["ai_score"] - score_minimum
            counts[ai_index][human_index] += 1
        image = ax.imshow(
            counts,
            origin="lower",
            cmap="Blues",
            vmin=0,
            aspect="equal",
        )
        ticks = list(range(size))
        labels = [str(score_minimum + index) for index in ticks]
        ax.set_xticks(ticks, labels)
        ax.set_yticks(ticks, labels)
        ax.set_xlabel("Human score")
        ax.set_ylabel("AI score")
        maximum_count = max(max(row_counts) for row_counts in counts)
        for y, row_counts in enumerate(counts):
            for x, count in enumerate(row_counts):
                if count:
                    color = "white" if count > maximum_count / 2 else "#17202a"
                    ax.text(x, y, str(count), ha="center", va="center", color=color)
        fig.colorbar(image, ax=ax, label="Response count", shrink=0.82)
    ax.set_title(f"Human and AI evaluator agreement\nResponse counts, n={len(rows)}")
    _save_figure(fig, output_path)


def _plot_decisions_by_model(
    rows: Sequence[Mapping[str, Any]], output_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    models = sorted({str(row["model_name"]) for row in rows})
    if not models:
        _show_empty(ax, "No model decisions")
    else:
        left = [0] * len(models)
        for decision in DECISION_ORDER:
            values = [
                sum(
                    row["model_name"] == model and row["decision"] == decision
                    for row in rows
                )
                for model in models
            ]
            ax.barh(
                models,
                values,
                left=left,
                label=decision,
                color=DECISION_COLORS[decision],
                edgecolor="#263238",
                linewidth=0.5,
            )
            left = [start + value for start, value in zip(left, values)]
        ax.set_xlim(left=0)
        ax.set_xlabel("Response count")
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.16),
            ncol=3,
            frameon=False,
        )
        ax.grid(axis="x", color="#d8dde3", linewidth=0.6)
        ax.set_axisbelow(True)
    ax.set_title(f"Decision distribution by model\nResponse counts, n={len(rows)}")
    _save_figure(fig, output_path)


def _plot_queue_by_severity(
    review_queue: Sequence[ReviewQueueItem], output_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    present = {
        str(item.record["error_severity"])
        for item in review_queue
    }
    severities = [severity for severity in SEVERITY_ORDER if severity in present]
    if not severities:
        _show_empty(ax, "No mandatory inspection or human-review cases")
    else:
        bottom = [0] * len(severities)
        for decision in ("FAIL", "HUMAN_REVIEW"):
            values = [
                sum(
                    item.record["error_severity"] == severity
                    and item.record["decision"] == decision
                    for item in review_queue
                )
                for severity in severities
            ]
            ax.bar(
                severities,
                values,
                bottom=bottom,
                label=decision,
                color=DECISION_COLORS[decision],
                edgecolor="#263238",
                linewidth=0.5,
            )
            bottom = [start + value for start, value in zip(bottom, values)]
        ax.set_ylim(bottom=0)
        ax.set_ylabel("Queue item count")
        ax.set_xlabel("Error severity")
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.2),
            ncol=2,
            frameon=False,
        )
        ax.grid(axis="y", color="#d8dde3", linewidth=0.6)
        ax.set_axisbelow(True)
    ax.set_title(
        "Human inspection queue by severity\n"
        f"FAIL and HUMAN_REVIEW cases, n={len(review_queue)}"
    )
    _save_figure(fig, output_path)


def _show_empty(ax: Any, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _save_figure(fig: Any, output_path: Path) -> None:
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    fig.savefig(
        output_path,
        dpi=144,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": "REC"},
    )
    plt.close(fig)
