"""
cross_validate.py
------------------
K-fold cross-validation runner for SentinelAI classifiers.

Rotates the validation fold across the train+val pool (dataset_v1_train.csv
+ dataset_v1_val.csv) via scripts/cv_utils.py's persisted StratifiedKFold
assignment, so baseline/DistilBERT/RoBERTa all rotate over identical folds.

dataset_v1_test.csv and probe_data/probe_data_v2.csv are never touched here --
CV is a validation-estimate step only. Once CV confirms a stable estimate,
retrain the shipped model on the full pool via train_baseline.py /
train_distilbert.py as usual and report the single-touch test/probe numbers
from those scripts, per reports/cross_validation_plan.md section 6.

Run:
  python scripts/cross_validate.py --model-type baseline
  python scripts/cross_validate.py --model-type distilbert
  python scripts/cross_validate.py --model-type roberta --k 5 --epochs 4
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from cv_utils import K, SEED, iter_folds, load_cv_pool
from evaluation import aggregate_cv_reports, save_cv_summary, save_report

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"

DEFAULT_RUN_NAMES = {
    "baseline": "baseline_tfidf_lr",
    "distilbert": "distilbert_v1",
    "roberta": "roberta_v1",
}
DEFAULT_HF_MODELS = {
    "distilbert": "distilbert-base-uncased",
    "roberta": "roberta-base",
}


def run_baseline_cv(pool, k: int, seed: int, rebuild_folds: bool):
    from evaluation import evaluate
    from train_baseline import build_pipeline, make_classify_fn

    reports = []
    for fold_id, train_df, val_df in iter_folds(pool, k=k, seed=seed, rebuild=rebuild_folds):
        print(f"\n=== fold {fold_id}/{k - 1}: train={len(train_df)}  val={len(val_df)} ===")
        pipe = build_pipeline()
        pipe.fit(train_df["prompt"].tolist(), train_df["label"].to_numpy())
        classify_fn = make_classify_fn(pipe)
        report = evaluate(f"baseline_tfidf_lr_fold{fold_id}", val_df, classify_fn)
        reports.append(report)
        h = report.headline
        print(f"  fold {fold_id}: acc={h.accuracy:.3f}  f1={h.f1:.3f}")
    return reports


def run_transformer_cv(hf_model: str, run_name: str, pool, k: int, seed: int,
                       rebuild_folds: bool, epochs: int, batch_size: int,
                       learning_rate: float, max_length: int):
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    from evaluation import evaluate
    from train_distilbert import PromptDataset, compute_metrics, make_classify_fn, set_seed

    set_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cpu":
        print("WARNING: CV on CPU will be very slow across multiple folds. "
              "Use a GPU runtime (e.g. Colab T4).")

    tmp_root = MODELS / "_cv_tmp" / run_name
    reports = []

    for fold_id, train_df, val_df in iter_folds(pool, k=k, seed=seed, rebuild=rebuild_folds):
        print(f"\n=== fold {fold_id}/{k - 1}: train={len(train_df)}  val={len(val_df)} ===")

        tokenizer = AutoTokenizer.from_pretrained(hf_model)
        # Fresh pretrained checkpoint every fold -- never continue training a
        # model that already saw a different fold's validation rows.
        model = AutoModelForSequenceClassification.from_pretrained(
            hf_model, num_labels=2,
            id2label={0: "benign", 1: "malicious"},
            label2id={"benign": 0, "malicious": 1},
        )

        train_ds = PromptDataset(train_df["prompt"].tolist(), train_df["label"].tolist(),
                                 tokenizer, max_length=max_length)
        val_ds = PromptDataset(val_df["prompt"].tolist(), val_df["label"].tolist(),
                               tokenizer, max_length=max_length)

        fold_dir = tmp_root / f"fold{fold_id}"
        fold_dir.mkdir(parents=True, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=str(fold_dir / "checkpoints"),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size * 2,
            learning_rate=learning_rate,
            weight_decay=0.01,
            warmup_steps=int(0.1 * epochs * (len(train_df) // batch_size)),
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            metric_for_best_model="f1",
            greater_is_better=True,
            logging_steps=20,
            save_total_limit=1,
            seed=seed,
            fp16=(device == "cuda"),
            report_to=[],
            disable_tqdm=False,
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            processing_class=tokenizer,
            data_collator=DataCollatorWithPadding(tokenizer),
            compute_metrics=compute_metrics,
        )
        trainer.train()

        classify_fn = make_classify_fn(model.to(device), tokenizer, device,
                                       max_length=max_length, batch_size=batch_size * 2)
        report = evaluate(f"{run_name}_fold{fold_id}", val_df, classify_fn, batch_size=64)
        reports.append(report)
        h = report.headline
        print(f"  fold {fold_id}: acc={h.accuracy:.3f}  f1={h.f1:.3f}")

        # Only the metrics are needed per fold -- discard weights immediately
        # so 5 folds don't multiply disk usage 5x for no benefit.
        del trainer, model, tokenizer
        if device == "cuda":
            torch.cuda.empty_cache()
        shutil.rmtree(fold_dir, ignore_errors=True)

    shutil.rmtree(tmp_root, ignore_errors=True)
    try:
        tmp_root.parent.rmdir()  # remove models/_cv_tmp/ itself if now empty
    except OSError:
        pass  # not empty (another model type's CV is using it) or already gone
    return reports


def main(args: argparse.Namespace) -> int:
    pool = load_cv_pool()
    print(f"CV pool: {len(pool)} rows (train+val combined; "
          f"test.csv and probe_data untouched)")

    run_name = args.run_name or DEFAULT_RUN_NAMES[args.model_type]

    if args.model_type == "baseline":
        reports = run_baseline_cv(pool, args.k, args.seed, args.rebuild_folds)
    else:
        hf_model = args.hf_model or DEFAULT_HF_MODELS[args.model_type]
        print(f"HF model: {hf_model}")
        reports = run_transformer_cv(
            hf_model, run_name, pool, args.k, args.seed, args.rebuild_folds,
            args.epochs, args.batch_size, args.learning_rate, args.max_length,
        )

    summary = aggregate_cv_reports(run_name, reports)

    out_dir = REPORTS / "cv"
    for report in reports:
        save_report(report, out_dir)
    paths = save_cv_summary(summary, out_dir)

    print(f"\n=== CV summary: {run_name} ({len(reports)} folds) ===")
    for metric, s in summary["headline"].items():
        if s["mean"] is not None:
            print(f"  {metric}: {s['mean']:.3f} ± {s['std']:.3f}  "
                  f"(95% CI [{s['ci95_low']:.3f}, {s['ci95_high']:.3f}])")
    print(f"  per-fold reports: {out_dir.relative_to(ROOT)}/")
    print(f"  summary report:   {paths['markdown'].relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-type", choices=["baseline", "distilbert", "roberta"],
                        required=True)
    parser.add_argument("--hf-model", default=None,
                        help="Override HF model id (distilbert/roberta only).")
    parser.add_argument("--run-name", default=None,
                        help="Prefix for reports/cv output files. "
                             "Default derived from --model-type.")
    parser.add_argument("--k", type=int, default=K)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--rebuild-folds", action="store_true",
                        help="Recompute the fold assignment even if a cached one exists.")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=256)
    args = parser.parse_args()
    raise SystemExit(main(args))
