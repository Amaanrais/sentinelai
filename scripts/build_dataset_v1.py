"""
build_dataset_v1.py
-------------------
Merges all sources into a single labeled dataset.

Inputs:
  data/seed_pairs.csv               (handcrafted, attack-typed)
  data/raw/jailbreakbench.csv       (optional)
  data/raw/advbench.csv             (optional)
  data/raw/hh_helpful.csv           (optional)
  data/raw/verazuo_forbidden.csv    (optional)

Steps:
  1. Load whatever exists (script does not fail if a source is missing).
  2. Clean text  (whitespace, control chars, length filter).
  3. Heuristic attack_type tagging on un-typed malicious rows
     using the rule patterns also used by the runtime rule engine.
     This makes the dataset directly auditable against the policy file.
  4. Deduplicate by lowercased+normalised prompt.
  5. Balance benign:malicious ~ 1.2:1 by downsampling whichever side is larger.
  6. Stratified train/val/test split (70/15/15) on label*attack_type.
  7. Write data/dataset_v1.csv plus per-split files.

The dataset is the artefact your thesis evaluation chapter cites.
"""

from __future__ import annotations
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# ----- attack-type heuristics (must stay in sync with rules/policies.yaml) -----
# Order matters: first match wins, so put the most specific patterns first.
ATTACK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("role_play_authority", re.compile(
        r"\b(as a|i am a|i'm a|acting as|playing the role of)\s+"
        r"(police|officer|detective|nurse|doctor|surgeon|researcher|"
        r"professor|teacher|security (?:expert|researcher|consultant)|"
        r"penetration tester|red[- ]team|ciso|forensic|"
        r"journalist|lawyer|investigator|chemist|pharmacist|nurse|"
        r"government|military|intelligence)\b",
        re.IGNORECASE,
    )),
    ("educational_justification", re.compile(
        r"\b(for (educational|academic|research|training|safety|study) "
        r"purposes?|to (?:learn|teach|protect|prevent|defend|raise awareness)|"
        r"in order to (?:protect|prevent|defend))\b",
        re.IGNORECASE,
    )),
    ("hypothetical_framing", re.compile(
        r"\b(hypothetically|imagine|in a (?:fictional|hypothetical) (?:scenario|story)|"
        r"in a (?:novel|movie|game|story)|fictional|"
        r"what if|suppose|let'?s pretend|role[- ]play)\b",
        re.IGNORECASE,
    )),
    ("indirect_phrasing", re.compile(
        r"\b(so (?:i|we) can (?:protect|defend|prevent|secure)|"
        r"to better (?:protect|understand|defend)|"
        r"awareness (?:campaign|video|blog)|"
        r"to demonstrate (?:to|for))\b",
        re.IGNORECASE,
    )),
]

DEFAULT_MALICIOUS_TYPE = "operational_request"


def normalise(text: str) -> str:
    """Lowercased, whitespace-collapsed key for dedup."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_prompt(text: str) -> str:
    text = text.replace("\r", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def infer_attack_type(prompt: str) -> str:
    for name, pat in ATTACK_PATTERNS:
        if pat.search(prompt):
            return name
    return DEFAULT_MALICIOUS_TYPE


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  - skip (not found): {path.relative_to(ROOT)}")
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"  + loaded {len(rows):>5} rows from {path.relative_to(ROOT)}")
    return rows


def merge_all() -> list[dict]:
    print("[1/6] Loading sources")
    rows: list[dict] = []
    rows += load_csv(DATA / "seed_pairs.csv")
    rows += load_csv(RAW / "jailbreakbench.csv")
    rows += load_csv(RAW / "advbench.csv")
    rows += load_csv(RAW / "hh_helpful.csv")
    rows += load_csv(RAW / "verazuo_forbidden.csv")
    return rows


def clean(rows: list[dict]) -> list[dict]:
    print("[2/6] Cleaning text and filtering by length")
    out = []
    for r in rows:
        prompt = clean_prompt(r.get("prompt", "") or "")
        if not (10 <= len(prompt) <= 1500):
            continue
        try:
            label = int(r.get("label", 0))
        except (TypeError, ValueError):
            continue
        if label not in (0, 1):
            continue
        out.append({
            "prompt": prompt,
            "label": label,
            "attack_type": (r.get("attack_type") or "none").strip() or "none",
            "topic": (r.get("topic") or "unknown").strip() or "unknown",
            "source": (r.get("source") or "unknown").strip() or "unknown",
        })
    print(f"      kept {len(out)} of {len(rows)} after cleaning")
    return out


def tag_attack_types(rows: list[dict]) -> list[dict]:
    """For malicious rows whose attack_type was not pre-set by hand, infer it."""
    print("[3/6] Heuristically tagging attack_type on un-typed malicious rows")
    changed = 0
    for r in rows:
        if r["label"] != 1:
            r["attack_type"] = "none"
            continue
        if r["attack_type"] in (None, "", "none", "unknown"):
            r["attack_type"] = infer_attack_type(r["prompt"])
            changed += 1
    print(f"      tagged {changed} rows")
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    print("[4/6] Deduplicating by normalised prompt")
    seen: dict[str, dict] = {}
    # Prefer handcrafted rows when duplicates appear (richer attack_type info).
    priority = {"handcrafted_seed_v1": 0}    # lower = preferred
    for r in rows:
        key = normalise(r["prompt"])
        if not key:
            continue
        prev = seen.get(key)
        if prev is None:
            seen[key] = r
            continue
        if priority.get(r["source"], 1) < priority.get(prev["source"], 1):
            seen[key] = r
    deduped = list(seen.values())
    print(f"      {len(rows)} -> {len(deduped)} unique prompts")
    return deduped


def balance(rows: list[dict], ratio_benign_to_malicious: float = 1.2) -> list[dict]:
    print(f"[5/6] Balancing classes (target benign:malicious = {ratio_benign_to_malicious}:1)")
    benign = [r for r in rows if r["label"] == 0]
    malicious = [r for r in rows if r["label"] == 1]
    random.shuffle(benign)
    random.shuffle(malicious)

    target_benign = int(len(malicious) * ratio_benign_to_malicious)
    if len(benign) > target_benign:
        benign = benign[:target_benign]
    # If we have far fewer benign than needed, leave it — never upsample
    # the benign side just to inflate counts (would create duplicates we
    # already removed).

    out = benign + malicious
    random.shuffle(out)
    print(f"      final: benign={len(benign)}  malicious={len(malicious)}  "
          f"total={len(out)}")
    return out


def split(rows: list[dict]) -> dict[str, list[dict]]:
    """Stratified split on label+attack_type so each split sees every category."""
    print("[6/6] Stratified train/val/test split (70/15/15)")
    buckets: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in rows:
        buckets[(r["label"], r["attack_type"])].append(r)

    train, val, test = [], [], []
    for key, items in buckets.items():
        random.shuffle(items)
        n = len(items)
        n_train = int(n * 0.70)
        n_val = int(n * 0.15)
        train += items[:n_train]
        val   += items[n_train:n_train + n_val]
        test  += items[n_train + n_val:]

    random.shuffle(train); random.shuffle(val); random.shuffle(test)
    print(f"      train={len(train)}  val={len(val)}  test={len(test)}")
    return {"train": train, "val": val, "test": test}


def write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["prompt", "label", "attack_type", "topic", "source"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def stats(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "benign": sum(1 for r in rows if r["label"] == 0),
        "malicious": sum(1 for r in rows if r["label"] == 1),
        "by_attack_type": dict(Counter(r["attack_type"] for r in rows)),
        "by_source": dict(Counter(r["source"] for r in rows)),
        "by_topic_top10": dict(Counter(r["topic"] for r in rows).most_common(10)),
    }


def main() -> int:
    rows = merge_all()
    if not rows:
        print("No source data found. Run scripts/fetch_public_sources.py first "
              "or create data/seed_pairs.csv via build_seed_dataset.py.",
              file=sys.stderr)
        return 1

    rows = clean(rows)
    rows = tag_attack_types(rows)
    rows = dedupe(rows)
    rows = balance(rows)
    splits = split(rows)

    write_csv(DATA / "dataset_v1.csv", rows)
    write_csv(DATA / "dataset_v1_train.csv", splits["train"])
    write_csv(DATA / "dataset_v1_val.csv",   splits["val"])
    write_csv(DATA / "dataset_v1_test.csv",  splits["test"])

    summary = {
        "overall": stats(rows),
        "train":   stats(splits["train"]),
        "val":     stats(splits["val"]),
        "test":    stats(splits["test"]),
        "random_seed": RANDOM_SEED,
    }
    with (DATA / "dataset_v1_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=== dataset_v1 written ===")
    print(json.dumps(summary["overall"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
