"""
cv_utils.py
-----------
Shared k-fold cross-validation utilities for SentinelAI classifiers.

Builds/persists a fixed StratifiedKFold assignment over the combined
train+val pool (dataset_v1_train.csv + dataset_v1_val.csv) so every model
(baseline, DistilBERT, RoBERTa) rotates over identical folds. dataset_v1_test.csv
and probe_data/probe_data_v2.csv are never touched here -- they remain
single-touch holdouts for the final reported metrics.

See reports/cross_validation_plan.md for the full design rationale.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd
from sklearn.model_selection import StratifiedKFold

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SEED = 42
K = 5

FOLDS_PATH = DATA / "dataset_v1_cv_folds.csv"


def load_cv_pool() -> pd.DataFrame:
    """train.csv + val.csv combined. test.csv is intentionally excluded."""
    train_df = pd.read_csv(DATA / "dataset_v1_train.csv")
    val_df = pd.read_csv(DATA / "dataset_v1_val.csv")
    return pd.concat([train_df, val_df], ignore_index=True)


def _composite_key(df: pd.DataFrame) -> pd.Series:
    return df["label"].astype(str) + "|" + df["attack_type"].astype(str)


def build_fold_assignment(pool: pd.DataFrame, k: int = K, seed: int = SEED) -> pd.DataFrame:
    """Assign each row a fold_id in [0, k) via StratifiedKFold on (label, attack_type).

    Falls back to label-only stratification if a composite cell is too small
    to have >= k members (same fallback pattern as build_dataset.py's
    stratified_split, just with a stricter per-cell minimum since
    StratifiedKFold needs >= k examples per class, not just >= 2)."""
    composite = _composite_key(pool)

    def _do_split(strat_col: pd.Series) -> pd.Series:
        skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
        fold_id = pd.Series(-1, index=pool.index, dtype=int)
        for fold, (_, val_idx) in enumerate(skf.split(pool, strat_col)):
            fold_id.iloc[val_idx] = fold
        return fold_id

    try:
        fold_id = _do_split(composite)
    except ValueError as e:
        print(f"  [!] Composite (label, attack_type) stratification failed ({e}); "
              f"falling back to label-only stratification.")
        fold_id = _do_split(pool["label"])

    return pd.DataFrame({"uid": pool["uid"], "fold_id": fold_id})


def get_or_build_folds(pool: pd.DataFrame, k: int = K, seed: int = SEED,
                        path: Path = FOLDS_PATH, rebuild: bool = False) -> pd.DataFrame:
    """Load the persisted fold assignment if it matches this pool/k, else (re)build it.

    Persisting is what guarantees baseline, DistilBERT, and RoBERTa all train
    and validate on identical folds for a fair comparison."""
    if path.exists() and not rebuild:
        folds = pd.read_csv(path)
        if set(folds["uid"]) == set(pool["uid"]) and folds["fold_id"].nunique() == k:
            return folds
        print(f"  [!] Existing fold assignment at {path} doesn't match the current "
              f"pool/k -- rebuilding.")

    folds = build_fold_assignment(pool, k=k, seed=seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    folds.to_csv(path, index=False)
    print(f"  [ok] Wrote fold assignment -> {path} ({k} folds, seed={seed})")
    return folds


def iter_folds(pool: pd.DataFrame, k: int = K, seed: int = SEED,
                path: Path = FOLDS_PATH, rebuild: bool = False
                ) -> Iterator[tuple[int, pd.DataFrame, pd.DataFrame]]:
    """Yield (fold_id, fold_train_df, fold_val_df) for each of the k rotations.

    Round i uses fold i as validation and the remaining k-1 folds as training,
    mirroring the rotation schedule in reports/cross_validation_plan.md."""
    folds = get_or_build_folds(pool, k=k, seed=seed, path=path, rebuild=rebuild)
    merged = pool.merge(folds, on="uid", validate="one_to_one")

    for fold_id in range(k):
        val_df = (merged[merged["fold_id"] == fold_id]
                  .drop(columns=["fold_id"]).reset_index(drop=True))
        train_df = (merged[merged["fold_id"] != fold_id]
                    .drop(columns=["fold_id"]).reset_index(drop=True))
        yield fold_id, train_df, val_df
