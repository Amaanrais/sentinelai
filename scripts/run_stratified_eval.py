"""
run_stratified_eval.py
----------------------
Runs all three SentinelAI classifiers on probe_data/probe_data.csv and
produces evaluation reports stratified by surface_benignity tier.

The 'tier' column is dropped — surface_benignity is our annotation.

Outputs:
    reports/stratified/distilbert_v1_report.{json,md}
    reports/stratified/roberta_v1_report.{json,md}
    reports/stratified/baseline_tfidf_report.{json,md}
    reports/stratified/cross_model_benignity.md
"""

from __future__ import annotations
from evaluation import evaluate, save_report, GroupedRecall, EvaluationReport
import pandas as pd
import numpy as np
import joblib

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


PROBE_DATA = ROOT / "probe_data" / "probe_data_v2.csv"
OUT_DIR = ROOT / "reports" / "stratified"
MODELS_DIR = ROOT / "models"

_TIER_LABELS = {0: "Obvious", 1: "Mild", 2: "Moderate", 3: "High"}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_probe_data() -> pd.DataFrame:
    df = pd.read_csv(PROBE_DATA)

    if "tier" in df.columns:
        df = df.drop(columns=["tier"])

    df["surface_benignity"] = df["surface_benignity"].astype(int)

    print(f"[*] Loaded {len(df)} prompts from probe_data")
    dist = df["surface_benignity"].value_counts().sort_index().to_dict()
    print(f"    surface_benignity distribution: {dist}")
    mal = (df["label"] == 1).sum()
    ben = (df["label"] == 0).sum()
    print(f"    labels: {mal} malicious / {ben} benign")
    print()
    return df


# --------------------------------------------------------------------------- #
# Classifier wrappers
# --------------------------------------------------------------------------- #

def _baseline_fn():
    path = MODELS_DIR / "baseline_tfidf_lr.joblib"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipeline = joblib.load(path)

    def _fn(prompts: list[str]):
        probs = pipeline.predict_proba(prompts)
        preds = probs.argmax(axis=1)
        return probs, preds

    return _fn


def _transformer_fn(model_dir: Path):
    from classifier import IntentClassifier
    clf = IntentClassifier.load(model_dir)
    return clf.as_classify_fn()


# --------------------------------------------------------------------------- #
# Cross-model comparison table
# --------------------------------------------------------------------------- #

def _cross_model_table(reports: list[EvaluationReport]) -> str:
    header_names = " | ".join(r.model_name for r in reports)
    sep = "|".join(["---"] * len(reports))

    lines = [
        "# Cross-model detection rate by surface_benignity tier\n",
        "Detection rate = recall on malicious prompts within each tier.\n",
        f"| tier | disguise level | n | {header_names} |",
        f"|------|----------------|---|{sep}|",
    ]

    for tier in [0, 1, 2, 3]:
        key = str(tier)
        label = _TIER_LABELS.get(tier, "?")
        n_str = "—"
        rates = []
        for r in reports:
            if r.per_benignity_tier and key in r.per_benignity_tier.by_group:
                g = r.per_benignity_tier.by_group[key]
                n_str = str(g["support"])
                rec = g["recall_on_positives"]
                rates.append(f"{rec:.3f}" if rec is not None else "—")
            else:
                rates.append("—")
        rate_str = " | ".join(rates)
        lines.append(f"| {tier} | {label} | {n_str} | {rate_str} |")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    df = load_probe_data()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    classifiers = [
        ("distilbert_v1", lambda: _transformer_fn(MODELS_DIR / "distilbert_v1")),
        ("roberta_v1", lambda: _transformer_fn(MODELS_DIR / "roberta_v1")),
        ("baseline_tfidf", _baseline_fn),
    ]

    reports = []
    for name, build_fn in classifiers:
        print(f"[*] Running {name} ...")
        report = evaluate(name, df, build_fn())
        save_report(report, OUT_DIR)
        reports.append(report)

        if report.per_benignity_tier:
            for tier in [0, 1, 2, 3]:
                key = str(tier)
                if key not in report.per_benignity_tier.by_group:
                    continue
                m = report.per_benignity_tier.by_group[key]
                rec = m["recall_on_positives"]
                rec_str = f"{rec:.1%}" if rec is not None else "—"
                label = _TIER_LABELS.get(tier, "?")
                print(
                    f"    Tier {tier} ({label:8s}, n={m['support']:3d}): {rec_str}")
        print()

    cross_md = _cross_model_table(reports)
    cross_path = OUT_DIR / "cross_model_benignity.md"
    cross_path.write_text(cross_md, encoding="utf-8")

    print("=" * 60)
    print(cross_md)
    print("=" * 60)
    print(f"\n[ok] Reports written to {OUT_DIR}")


if __name__ == "__main__":
    main()
