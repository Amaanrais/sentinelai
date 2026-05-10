"""
01_eda.py  (Jupyter percent format — open in VSCode / convert with jupytext)

Quick exploratory analysis of dataset_v1.  Run this after building the
dataset.  The plots and tables here are the ones to drop into the thesis
data chapter.

Open in VSCode with the Jupyter extension, or convert:
    pip install jupytext
    jupytext --to ipynb notebooks/01_eda.py
"""

# %% [markdown]
# # SentinelAI Phase 1 — EDA
#
# Sanity-checks the assembled dataset before model training.

# %%
import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

DATA = Path("..") / "data"
df = pd.read_csv(DATA / "dataset_v1.csv")
print(f"rows: {len(df):,}")
df.head()

# %% [markdown]
# ## Class balance

# %%
df["label"].value_counts().rename({0: "benign", 1: "malicious"})

# %% [markdown]
# ## Attack-type distribution (malicious only)

# %%
mal = df[df["label"] == 1]
mal["attack_type"].value_counts().plot.barh()
plt.title("Attack-type distribution — malicious prompts")
plt.xlabel("count")
plt.tight_layout()
plt.savefig(DATA / "fig_attack_type_distribution.png", dpi=150)
plt.show()

# %% [markdown]
# ## Source distribution

# %%
df["source"].value_counts()

# %% [markdown]
# ## Prompt-length distribution by class

# %%
df["len_chars"] = df["prompt"].str.len()
fig, ax = plt.subplots(figsize=(8, 4))
df[df["label"] == 0]["len_chars"].plot.hist(bins=40, alpha=0.6, label="benign", ax=ax)
df[df["label"] == 1]["len_chars"].plot.hist(bins=40, alpha=0.6, label="malicious", ax=ax)
ax.set_xlabel("prompt length (chars)")
ax.legend()
plt.tight_layout()
plt.savefig(DATA / "fig_length_by_class.png", dpi=150)
plt.show()

# %% [markdown]
# ## Per-split summaries (from the JSON the pipeline produced)

# %%
with (DATA / "dataset_v1_summary.json").open() as f:
    summary = json.load(f)
print(json.dumps(summary, indent=2))

# %% [markdown]
# ## Quick smell test: random sample of 5 from each class

# %%
print("=== BENIGN ===")
for p in df[df["label"] == 0].sample(min(5, (df["label"] == 0).sum()),
                                     random_state=0)["prompt"]:
    print(" -", p[:150])

print("\n=== MALICIOUS ===")
for p in df[df["label"] == 1].sample(min(5, (df["label"] == 1).sum()),
                                     random_state=0)["prompt"]:
    print(" -", p[:150])
