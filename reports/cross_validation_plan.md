# Technical plan: introducing k-fold cross-validation

Status: proposed (not yet implemented)
Author context: prepared for SentinelAI classifier training pipeline (baseline TF-IDF+LR, DistilBERT, RoBERTa)

## 1. Current state (as found in the codebase)

Dataset build (`scripts/build_dataset.py::stratified_split`) does a **single static 70/15/15 split**:

- `dataset_v1.csv` — 4,000 rows, hard-balanced 2,000 malicious / 2,000 benign (`enforce_balance`)
- Split via two sequential `sklearn.model_selection.train_test_split` calls, stratified on the **composite key `label|attack_type`** (falls back to label-only if a cell is too small):
  - `train_test_split(df, test_size=0.30, stratify=composite, random_state=42)` → train vs temp
  - `train_test_split(temp, test_size=0.50, stratify=temp_composite, random_state=42)` → val vs test
- Resulting files (confirmed from `data/dataset_v1_summary.json`):

| split | rows | malicious | benign |
|---|---:|---:|---:|
| train | 2,800 (70%) | 1,400 | 1,400 |
| val   | 600 (15%)   | 300   | 300   |
| test  | 600 (15%)   | 300   | 300   |

`RANDOM_SEED = 42` throughout.

Both training scripts consume these three fixed CSVs directly:

- `scripts/train_baseline.py`: fits TF-IDF+LR on `train`, does a one-line sanity check on `val` (`pipe.score`), reports final metrics on `test` once via `scripts/evaluation.py::evaluate`.
- `scripts/train_distilbert.py` (also mirrored in `notebooks/02_train_distilbert_colab.ipynb` for the `distilbert_v1` / `roberta_v1` runs): fits on `train`, uses `val` inside the HF `Trainer` for epoch-wise early-model-selection (`eval_strategy="epoch"`, `load_best_model_at_end=True`, `metric_for_best_model="f1"`), then reports final metrics on `test` once.

So today: **one fixed validation split**, used only for model selection (best epoch / early stopping), and **one fixed test split**, touched exactly once for the number that goes in the report. There is also a separate, never-touched OOD set (`probe_data/probe_data_v2.csv`) used by `run_stratified_eval.py` / `step3_harm_rate.py` / `run_attack_type_confusion.py` — that stays completely out of scope for this change.

## 2. Why introduce CV, and what it changes

A single 15% validation split means the reported val metric (and any early-stopping decision it drives) has sampling variance — a lucky/unlucky split can make a model look better or worse than it is. K-fold CV rotates the validation fold across the training pool so the reported metric is a mean ± variance estimate over multiple splits instead of one draw.

**What CV replaces:** the role currently played by `dataset_v1_val.csv`.
**What CV does not touch:** `dataset_v1_test.csv` and `probe_data_v2.csv` stay held out exactly as they are today — CV must never see them, or the final reported generalization numbers become optimistic.

## 3. Fold design

### 3.1 Pool

```
cv_pool = concat(dataset_v1_train.csv, dataset_v1_val.csv)   # 2,800 + 600 = 3,400 rows
test.csv (600 rows)      -> untouched, final holdout only
probe_data_v2.csv        -> untouched, OOD holdout only
```

### 3.2 Splitter

`sklearn.model_selection.StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`, stratified on the **same composite key** already used for the original split: `label.astype(str) + "|" + attack_type.astype(str)`.

- **k = 5** (20% val per fold): the standard default, keeps each validation fold close in size to the current 600-row val split, and keeps GPU cost for the transformer runs bounded (see §5). If a `(label, attack_type)` cell is too small to survive 5-way stratification, fall back to label-only stratification — same fallback pattern already used in `stratified_split`.
- **Same `random_state=42`** as the rest of the pipeline, for reproducibility and thesis citability.

### 3.3 Rotation mechanism

Fold membership is computed **once** and persisted, so every model (baseline, DistilBERT, RoBERTa) trains/validates on **identical folds** — required for an apples-to-apples comparison in the results chapter.

1. Run `StratifiedKFold.split(cv_pool, composite_key)` once → 5 `(train_idx, val_idx)` pairs.
2. Persist as `data/dataset_v1_cv_folds.csv`: columns `uid, fold_id` (fold_id ∈ {0..4}), joined back to `cv_pool` by the existing `uid` column.
3. Rotation schedule — each round, one fold is validation, the other four are concatenated to form that round's training set:

| round | val fold | train folds |
|---|---|---|
| 1 | 0 | 1,2,3,4 |
| 2 | 1 | 0,2,3,4 |
| 3 | 2 | 0,1,3,4 |
| 4 | 3 | 0,1,2,4 |
| 5 | 4 | 0,1,2,3 |

Every row in `cv_pool` is validated on exactly once and trained on exactly four times.

### 3.4 Known leakage risk (flag, not blocker)

A meaningful share of malicious rows are template-generated (`FICTIONAL_FRAMES`, `AUTHORITY_FRAMES`, `RAG_TEMPLATES` in `build_dataset.py`) or LLM-grid-generated within an `(attack_type, tier)` cell. Exact duplicates are already removed (`deduplicate()` hashes on normalized prompt text), but **near-duplicate phrasing** from the same template/cell can still land in different folds and inflate CV scores slightly versus true generalization. This risk already existed in the single train/val/test split — CV doesn't introduce it, just makes it worth naming. Mitigation for a future dataset revision: persist a `gen_batch_id` (template family / grid cell) during generation and use `StratifiedGroupKFold` instead of `StratifiedKFold` so an entire batch stays on one side of the fold. Out of scope for this plan; call out as a limitation in the thesis methodology section.

## 4. Per-model procedure

### 4.1 Baseline (TF-IDF + LR) — cheap, ~seconds/fold

For each of the 5 folds:
1. Build a **fresh** `Pipeline` via `train_baseline.py::build_pipeline()` (must re-fit the vectorizer per fold — fitting TF-IDF on the full pool first and only rotating the classifier would leak vocabulary/IDF statistics from validation rows into training).
2. Fit on fold-train, evaluate on fold-val with `scripts/evaluation.py::evaluate()`.
3. Save `reports/cv/baseline_tfidf_lr_fold{i}_report.json`.

Total cost: 5 fits, negligible (current single fit is already sub-second on CPU).

### 4.2 Transformers (DistilBERT / RoBERTa) — expensive, ~5-10 min/fold on T4

For each of the 5 folds:
1. Reload the **pretrained** checkpoint fresh (`AutoModelForSequenceClassification.from_pretrained(args.model, ...)`) — never continue training a model that saw a different fold, or later folds inherit leaked signal from earlier folds' validation rows.
2. Same fixed hyperparameters as the current single run (epochs, batch size, LR) — CV here is for **estimating validation-metric variance**, not per-fold hyperparameter search (that would multiply cost by however many configs are tried).
3. `Trainer` with `eval_strategy="epoch"`, `load_best_model_at_end=True`, `metric_for_best_model="f1"` on fold-val, exactly as today.
4. Evaluate the fold's best-epoch model on fold-val via the shared harness, save `reports/cv/{run_name}_fold{i}_report.json`.
5. Delete the fold's checkpoints/weights immediately after scoring (`shutil.rmtree`, same cleanup already done post-training) — only metrics are needed per fold; retaining 5 full model directories per transformer would multiply disk usage 5x for no benefit.

Total cost estimate: 5 folds x ~5-10 min = **25-50 min per transformer model** on a T4, so ~1-1.5 hrs for DistilBERT + RoBERTa combined in one Colab session. This is the main reason k=5 (not 10) is recommended.

## 5. Aggregation

Add `aggregate_cv_reports(reports: list[EvaluationReport]) -> dict` to `scripts/evaluation.py`:

- Per headline metric (accuracy, precision, recall, F1, ROC-AUC, PR-AUC): mean, std, and a 95% CI using the t-distribution (k=5 → t-critical, not normal-approx, given the small fold count).
- Per-attack-type recall and per-benignity-tier recall: mean recall across the folds where that group had support (some rare `attack_type` cells may not appear in every fold at n=3,400/5≈680 per fold — report `folds_with_support` alongside the mean so a mean over 2 folds isn't presented with the same confidence as a mean over 5).
- Output: `reports/cv/{model}_cv_summary.json` and `.md` (reuse `render_markdown`-style formatting for consistency with existing reports).

## 6. Final model fit (unchanged reporting contract)

CV is a **validation-estimate step**, not a replacement for the final shipped model or the final reported test number:

1. After CV confirms stable performance (and, if a hyperparameter sweep is added later, selects the best config), retrain **one final model** on the full `cv_pool` (train+val combined, 3,400 rows) using the CV-validated settings.
2. Evaluate that single final model **once** on the still-untouched `dataset_v1_test.csv` (600 rows) — this becomes the number in `reports/{model}_report.md`, exactly as today.
3. `probe_data_v2.csv` OOD evaluation (`run_stratified_eval.py`, `step3_harm_rate.py`, `run_attack_type_confusion.py`) also runs once against this final model, unchanged.
4. This final model is what gets saved to `models/{baseline_tfidf_lr,distilbert_v1,roberta_v1}/`.

Net effect on the thesis narrative: CV mean±std shows the validation estimate is stable (robustness claim); the untouched test.csv and probe_data_v2.csv numbers remain the headline generalization and OOD claims, each touched exactly once, so no CV rotation ever leaks into a reported test number.

## 7. Implementation checklist

- [ ] `scripts/cv_utils.py` (new): builds/persists `data/dataset_v1_cv_folds.csv`, exposes `iter_folds(cv_pool_df, k=5, seed=42) -> Iterator[(fold_id, train_df, val_df)]`.
- [ ] `scripts/evaluation.py`: add `aggregate_cv_reports()`.
- [ ] `scripts/cross_validate.py` (new): CLI with `--model-type {baseline,distilbert,roberta}`, `--k 5`, `--seed 42`; imports `build_pipeline()` from `train_baseline.py` and the model/tokenizer loading + `PromptDataset` from `train_distilbert.py` rather than duplicating training logic.
- [ ] `notebooks/02_train_distilbert_colab.ipynb`: mirror the same per-fold loop (it currently duplicates `train_distilbert.py`'s logic for the free-GPU workflow).
- [ ] `reports/cv/` output directory for per-fold + summary reports.
- [ ] Thesis methodology section: document k=5 stratified CV on `label|attack_type`, seed=42, the near-duplicate leakage caveat (§3.4), and the "CV for robustness, single-touch test/probe for generalization" contract (§6).
