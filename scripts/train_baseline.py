"""
train_baseline.py
-----------------
Baseline classifier: TF-IDF (word + char n-grams) + Logistic Regression.

Purpose: give the thesis a 'traditional NLP' lower bound to benchmark the
DistilBERT fine-tune against.  This directly addresses RQ2:
    'How effective are fine-tuned transformers compared to traditional NLP?'

Trains in seconds on CPU. No GPU needed.

Outputs:
  models/baseline_tfidf_lr.joblib    serialised pipeline
  reports/baseline_report.json       structured metrics
  reports/baseline_report.md         human-readable for thesis appendix
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from evaluation import evaluate, save_report

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"


def build_pipeline() -> Pipeline:
    """Word-level + character-level TF-IDF, then LR.

    Why both?  Disguised malicious prompts often share *phrases* with benign
    counterparts ('for educational purposes'); word n-grams pick those up.
    Character n-grams catch obfuscation (l33t-speak, leetspeak, splits)
    that survives in real adversarial settings.
    """
    word_vec = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.95,
        sublinear_tf=True,
        lowercase=True,
        strip_accents="unicode",
    )
    char_vec = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        min_df=2,
        max_df=0.95,
        sublinear_tf=True,
        lowercase=True,
        strip_accents="unicode",
    )
    features = FeatureUnion([("word", word_vec), ("char", char_vec)])

    clf = LogisticRegression(
        C=1.0,
        max_iter=2000,
        class_weight="balanced",
        solver="liblinear",   # works well with sparse TF-IDF
        random_state=42,
    )
    return Pipeline([("features", features), ("clf", clf)])


def make_classify_fn(pipe: Pipeline):
    def classify(prompts: list[str]):
        probs = pipe.predict_proba(prompts)
        preds = probs.argmax(axis=1)
        return probs, preds
    return classify


def main(args: argparse.Namespace) -> int:
    train_df = pd.read_csv(DATA / "dataset_v1_train.csv")
    val_df   = pd.read_csv(DATA / "dataset_v1_val.csv")
    test_df  = pd.read_csv(DATA / "dataset_v1_test.csv")

    print(f"train={len(train_df):,}  val={len(val_df):,}  test={len(test_df):,}")
    if len(train_df) < 30:
        print("WARNING: very small dataset. Run scripts/build_dataset.py first.")

    print("\nFitting pipeline ...")
    t0 = time.time()
    pipe = build_pipeline()
    pipe.fit(train_df["prompt"].tolist(), train_df["label"].to_numpy())
    print(f"  fit done in {time.time() - t0:.1f}s")

    # quick val sanity
    val_acc = pipe.score(val_df["prompt"].tolist(), val_df["label"].to_numpy())
    print(f"  val accuracy: {val_acc:.3f}")

    # full eval on test
    print("\nEvaluating on test split ...")
    classify_fn = make_classify_fn(pipe)
    report = evaluate(
        model_name="baseline_tfidf_lr",
        test_df=test_df,
        classify_fn=classify_fn,
    )

    MODELS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    model_path = MODELS / "baseline_tfidf_lr.joblib"
    joblib.dump(pipe, model_path)
    print(f"\nSaved model    -> {model_path.relative_to(ROOT)}")

    paths = save_report(report, REPORTS)
    print(f"Saved report   -> {paths['markdown'].relative_to(ROOT)}")
    print(f"Saved JSON     -> {paths['json'].relative_to(ROOT)}")

    h = report.headline
    print(f"\n=== {report.model_name} ===")
    print(f"  acc={h.accuracy:.3f}  prec={h.precision:.3f}  "
          f"rec={h.recall:.3f}  f1={h.f1:.3f}  "
          f"roc_auc={h.roc_auc:.3f}" if h.roc_auc else "")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    raise SystemExit(main(args))
