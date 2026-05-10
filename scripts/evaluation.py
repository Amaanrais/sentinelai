"""
evaluation.py
-------------
Model-agnostic evaluation harness for SentinelAI classifiers.

Both the TF-IDF baseline (Phase 2a) and the DistilBERT fine-tune (Phase 2b)
import from this module so their reports are directly comparable.

A 'classifier' is any callable f(list[str]) -> (probs[N,2], preds[N]).

What this module reports (these are what the thesis evaluation chapter cites):

  1. Headline metrics
       accuracy, precision, recall, F1 (binary), ROC-AUC, PR-AUC
  2. Confusion matrix
  3. Per-attack-type recall            <-- answers RQ3
  4. Per-source recall                 <-- generalisation evidence
  5. Per-topic recall                  <-- topical fairness
  6. Probability-calibration summary   <-- needed for fusion thresholds in Phase 4
  7. Misclassified examples (top 20)   <-- error analysis for thesis
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)

ClassifyFn = Callable[[list[str]], tuple[np.ndarray, np.ndarray]]


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #

@dataclass
class HeadlineMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | None
    pr_auc: float | None
    n: int
    n_positive: int


@dataclass
class GroupedRecall:
    """Recall broken down by an arbitrary categorical column (attack_type, source, topic)."""
    by_group: dict[str, dict[str, float | int]] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    model_name: str
    headline: HeadlineMetrics
    confusion_matrix: list[list[int]]    # [[tn,fp],[fn,tp]]
    per_attack_type: GroupedRecall
    per_source: GroupedRecall
    per_topic_top10: GroupedRecall
    calibration: dict[str, float]
    top_misclassified: list[dict]


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #

def headline(y_true: np.ndarray, y_pred: np.ndarray,
             y_prob: np.ndarray | None) -> HeadlineMetrics:
    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", pos_label=1, zero_division=0
    )
    roc = pr = None
    if y_prob is not None and len(np.unique(y_true)) == 2:
        roc = float(roc_auc_score(y_true, y_prob))
        pr = float(average_precision_score(y_true, y_prob))
    return HeadlineMetrics(
        accuracy=float(accuracy_score(y_true, y_pred)),
        precision=float(p),
        recall=float(r),
        f1=float(f1),
        roc_auc=roc,
        pr_auc=pr,
        n=int(len(y_true)),
        n_positive=int((y_true == 1).sum()),
    )


def _grouped_recall(df: pd.DataFrame, col: str,
                    min_support: int = 1,
                    top_n: int | None = None) -> GroupedRecall:
    out: dict[str, dict[str, float | int]] = {}
    counts = df[col].value_counts()
    keys = list(counts.index)
    if top_n is not None:
        keys = keys[:top_n]
    for key in keys:
        sub = df[df[col] == key]
        if len(sub) < min_support:
            continue
        # Recall is only defined for positives. For benign-only groups (e.g. attack_type='none')
        # we report specificity instead so the column is never empty.
        positives = sub[sub["y_true"] == 1]
        negatives = sub[sub["y_true"] == 0]
        rec = (
            float((positives["y_pred"] == 1).mean())
            if len(positives) else None
        )
        spec = (
            float((negatives["y_pred"] == 0).mean())
            if len(negatives) else None
        )
        out[str(key)] = {
            "support": int(len(sub)),
            "positives": int(len(positives)),
            "negatives": int(len(negatives)),
            "recall_on_positives": rec,
            "specificity_on_negatives": spec,
        }
    return GroupedRecall(by_group=out)


def _calibration(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float]:
    """Cheap calibration summary: bucket-mean prob vs bucket-mean label, ECE."""
    if y_prob is None:
        return {}
    bins = np.linspace(0.0, 1.0, 11)
    idx = np.clip(np.digitize(y_prob, bins) - 1, 0, 9)
    ece = 0.0
    for b in range(10):
        mask = idx == b
        if not mask.any():
            continue
        bucket_prob = y_prob[mask].mean()
        bucket_acc = y_true[mask].mean()
        ece += (mask.sum() / len(y_true)) * abs(bucket_prob - bucket_acc)
    return {"expected_calibration_error_10bin": float(ece)}


def _top_misclassified(df: pd.DataFrame, k: int = 20) -> list[dict]:
    wrong = df[df["y_true"] != df["y_pred"]].copy()
    if "y_prob" in wrong.columns:
        # for FN show how 'wrong' the model was; for FP same thing on the other side
        wrong["confidence_in_wrong_answer"] = np.where(
            wrong["y_pred"] == 1, wrong["y_prob"], 1 - wrong["y_prob"]
        )
        wrong = wrong.sort_values("confidence_in_wrong_answer", ascending=False)
    out = []
    for _, row in wrong.head(k).iterrows():
        out.append({
            "prompt": row["prompt"][:280],
            "y_true": int(row["y_true"]),
            "y_pred": int(row["y_pred"]),
            "y_prob": (float(row["y_prob"]) if "y_prob" in row else None),
            "attack_type": row.get("attack_type", "?"),
            "source": row.get("source", "?"),
            "topic": row.get("topic", "?"),
        })
    return out


def evaluate(model_name: str,
             test_df: pd.DataFrame,
             classify_fn: ClassifyFn,
             batch_size: int = 64) -> EvaluationReport:
    """Run a full evaluation. test_df must have columns:
       prompt, label, attack_type, source, topic"""

    prompts = test_df["prompt"].tolist()
    y_true = test_df["label"].to_numpy()

    # batched inference so big test sets don't OOM
    probs_all, preds_all = [], []
    for i in range(0, len(prompts), batch_size):
        batch = prompts[i:i + batch_size]
        probs, preds = classify_fn(batch)
        probs_all.append(np.asarray(probs))
        preds_all.append(np.asarray(preds))
    probs = np.vstack(probs_all)
    y_pred = np.concatenate(preds_all).astype(int)
    y_prob = probs[:, 1] if probs.ndim == 2 else probs   # P(malicious)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()

    df = test_df.copy()
    df["y_true"] = y_true
    df["y_pred"] = y_pred
    df["y_prob"] = y_prob

    return EvaluationReport(
        model_name=model_name,
        headline=headline(y_true, y_pred, y_prob),
        confusion_matrix=cm,
        per_attack_type=_grouped_recall(df, "attack_type"),
        per_source=_grouped_recall(df, "source"),
        per_topic_top10=_grouped_recall(df, "topic", top_n=10),
        calibration=_calibration(y_true, y_prob),
        top_misclassified=_top_misclassified(df, k=20),
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def render_markdown(report: EvaluationReport) -> str:
    h = report.headline
    cm = report.confusion_matrix
    lines: list[str] = []
    lines.append(f"# Evaluation report — {report.model_name}\n")
    lines.append("## Headline metrics\n")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    for k, v in asdict(h).items():
        lines.append(f"| {k} | {_fmt(v)} |")
    lines.append("\n## Confusion matrix\n")
    lines.append("|              | pred benign | pred malicious |")
    lines.append("|--------------|-------------|----------------|")
    lines.append(f"| **true benign**    | {cm[0][0]} | {cm[0][1]} |")
    lines.append(f"| **true malicious** | {cm[1][0]} | {cm[1][1]} |")

    def _grouped_table(title: str, gr: GroupedRecall):
        lines.append(f"\n## {title}\n")
        lines.append("| group | support | pos | neg | recall (pos) | specificity (neg) |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for grp, m in sorted(gr.by_group.items(),
                             key=lambda kv: -kv[1]["support"]):
            lines.append(
                f"| {grp} | {m['support']} | {m['positives']} | "
                f"{m['negatives']} | {_fmt(m['recall_on_positives'])} | "
                f"{_fmt(m['specificity_on_negatives'])} |"
            )

    _grouped_table("Per attack type (RQ3)", report.per_attack_type)
    _grouped_table("Per source", report.per_source)
    _grouped_table("Per topic (top 10)", report.per_topic_top10)

    if report.calibration:
        lines.append("\n## Calibration\n")
        for k, v in report.calibration.items():
            lines.append(f"- **{k}**: {_fmt(v)}")

    lines.append("\n## Top 20 misclassifications (highest-confidence wrongs)\n")
    lines.append("| true | pred | prob | attack_type | source | prompt |")
    lines.append("|---|---|---:|---|---|---|")
    for m in report.top_misclassified:
        lines.append(
            f"| {m['y_true']} | {m['y_pred']} | "
            f"{_fmt(m['y_prob'])} | {m['attack_type']} | "
            f"{m['source']} | {m['prompt'].replace('|', '/')} |"
        )

    return "\n".join(lines)


def save_report(report: EvaluationReport, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{report.model_name}_report.json"
    md_path   = out_dir / f"{report.model_name}_report.md"

    payload = {
        "model_name": report.model_name,
        "headline": asdict(report.headline),
        "confusion_matrix": report.confusion_matrix,
        "per_attack_type": report.per_attack_type.by_group,
        "per_source": report.per_source.by_group,
        "per_topic_top10": report.per_topic_top10.by_group,
        "calibration": report.calibration,
        "top_misclassified": report.top_misclassified,
    }
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(render_markdown(report))
    return {"json": json_path, "markdown": md_path}


def compare_reports(reports: Iterable[EvaluationReport]) -> str:
    """Side-by-side comparison table for the thesis 'baseline vs transformer' figure."""
    reports = list(reports)
    lines = ["# Model comparison\n",
             "| metric | " + " | ".join(r.model_name for r in reports) + " |",
             "|---|" + "|".join(["---"] * len(reports)) + "|"]
    for k in ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"):
        row = [k] + [_fmt(getattr(r.headline, k)) for r in reports]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
