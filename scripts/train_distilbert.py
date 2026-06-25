"""
train_distilbert.py
-------------------
Fine-tune DistilBERT on dataset_v1 for binary intent classification.

Designed to run on:
  - Google Colab free GPU (T4)  -- ~5-10 minutes
  - Local NVIDIA GPU            -- similar
  - CPU                          -- works, takes ~30-60 minutes on dataset_v1

Outputs:
  models/distilbert_v1/                      HF-format model directory
  reports/distilbert_v1_report.{json,md}     evaluation report

Why DistilBERT:
  - 40% smaller than BERT-base, 60% faster, retains ~97% of GLUE performance
  - Fine-tunes well on small datasets (a few thousand examples)
  - Cheap enough for the runtime gateway in Phase 7

Run:
  python scripts/train_distilbert.py
  python scripts/train_distilbert.py --epochs 5 --batch-size 32  --model roberta-base
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

from evaluation import evaluate, save_report

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"

SEED = 42


def set_seed(seed: int = SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #

class PromptDataset(Dataset):
    def __init__(self, prompts: list[str], labels: list[int],
                 tokenizer, max_length: int = 256):
        self.encodings = tokenizer(
            prompts,
            truncation=True,
            max_length=max_length,
            padding=False,           # collator will pad per-batch
        )
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(int(self.labels[idx]))
        return item


# --------------------------------------------------------------------------- #
# Metrics for HF Trainer (evaluation during training)
# --------------------------------------------------------------------------- #

def compute_metrics(eval_pred):
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    p, r, f1, _ = precision_recall_fscore_support(
        labels, preds, average="binary", pos_label=1, zero_division=0
    )
    return {
        "accuracy": accuracy_score(labels, preds),
        "precision": p,
        "recall": r,
        "f1": f1,
    }


# --------------------------------------------------------------------------- #
# Inference wrapper for our shared evaluation harness
# --------------------------------------------------------------------------- #

def make_classify_fn(model, tokenizer, device, max_length: int = 256,
                     batch_size: int = 32):
    model.eval()

    def classify(prompts: list[str]):
        all_probs, all_preds = [], []
        with torch.no_grad():
            for i in range(0, len(prompts), batch_size):
                batch = prompts[i:i + batch_size]
                enc = tokenizer(batch, truncation=True, padding=True,
                                max_length=max_length, return_tensors="pt").to(device)
                logits = model(**enc).logits
                probs = torch.softmax(logits, dim=-1).cpu().numpy()
                preds = probs.argmax(axis=1)
                all_probs.append(probs)
                all_preds.append(preds)
        return np.vstack(all_probs), np.concatenate(all_preds)

    return classify


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(args):
    set_seed(args.seed)

    train_df = pd.read_csv(DATA / "dataset_v1_train.csv")
    val_df   = pd.read_csv(DATA / "dataset_v1_val.csv")
    test_df  = pd.read_csv(DATA / "dataset_v1_test.csv")
    print(f"train={len(train_df):,}  val={len(val_df):,}  test={len(test_df):,}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cpu":
        print("WARNING: training on CPU will be slow. Use Colab free GPU "
              "(Runtime -> Change runtime type -> T4 GPU).")

    print(f"\nLoading model: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=2,
        id2label={0: "benign", 1: "malicious"},
        label2id={"benign": 0, "malicious": 1},
    )

    train_ds = PromptDataset(
        train_df["prompt"].tolist(), train_df["label"].tolist(),
        tokenizer, max_length=args.max_length,
    )
    val_ds = PromptDataset(
        val_df["prompt"].tolist(), val_df["label"].tolist(),
        tokenizer, max_length=args.max_length,
    )

    out_dir = MODELS / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        warmup_steps=int(0.1 * args.epochs * (len(train_df) // args.batch_size)),
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        logging_steps=20,
        save_total_limit=2,
        seed=args.seed,
        fp16=(device == "cuda"),     # mixed precision on GPU
        report_to=[],                # disable wandb/tensorboard
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

    print("\n>>> Training")
    trainer.train()

    print("\n>>> Saving best model")
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    # Cleanup intermediate checkpoints to save disk
    import shutil
    shutil.rmtree(out_dir / "checkpoints", ignore_errors=True)

    # Save training config alongside the model so the thesis can cite it
    with (out_dir / "training_config.json").open("w") as f:
        json.dump(vars(args), f, indent=2)

    # >>> Full evaluation using the shared harness
    print("\n>>> Evaluating on test split")
    classify_fn = make_classify_fn(
        model.to(device), tokenizer, device,
        max_length=args.max_length, batch_size=args.batch_size * 2,
    )
    report = evaluate(args.run_name, test_df, classify_fn, batch_size=64)

    REPORTS.mkdir(exist_ok=True)
    paths = save_report(report, REPORTS)

    h = report.headline
    print(f"\n=== {report.model_name} ===")
    print(f"  acc={h.accuracy:.3f}  prec={h.precision:.3f}  "
          f"rec={h.recall:.3f}  f1={h.f1:.3f}  "
          f"roc_auc={h.roc_auc:.3f}  pr_auc={h.pr_auc:.3f}")
    print(f"  report: {paths['markdown'].relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="distilbert-base-uncased",
                        help="HF model id. Try roberta-base for stronger results.")
    parser.add_argument("--run-name", default="distilbert_v1",
                        help="Output subdir under models/ and metric prefix.")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    raise SystemExit(main(args))
