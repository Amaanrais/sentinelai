"""
fetch_public_sources.py
-----------------------
Pulls the public datasets that anchor the SentinelAI training corpus.

Run this on a machine with internet access. It does not require GPU.

Sources fetched:
  1. JailbreakBench harmful-behaviors    (HuggingFace: JailbreakBench/JBB-Behaviors)
  2. AdvBench harmful behaviors          (GitHub raw CSV from the original paper)
  3. Anthropic HH-RLHF helpful split     (HuggingFace: Anthropic/hh-rlhf, helpful-base)
  4. Awesome ChatGPT jailbreak prompts   (GitHub raw CSV from a maintained list)

Output: data/raw/<source>.csv  (one file per source, raw text + minimal labels)
        data/raw/_summary.json (counts + provenance for the thesis appendix)

Notes
-----
- We do NOT redistribute the source data inside this repo. We pull at run time.
- Each source's terms of use should be reviewed before publication. License
  notes are recorded in _summary.json so the thesis can cite them.
- If a source is unreachable, the script logs the failure and continues; do not
  block the pipeline on a single source being down.
"""

from __future__ import annotations
import csv
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SourceResult:
    name: str
    url: str
    rows_written: int
    license_note: str
    status: str           # "ok" | "skipped" | "error"
    error: Optional[str] = None


# ---------------- helpers ----------------

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _try(name: str, url: str, license_note: str,
         fn: Callable[[], list[dict]],
         out_file: str,
         fieldnames: list[str]) -> SourceResult:
    print(f"\n[+] Fetching {name} ...")
    try:
        rows = fn()
        if not rows:
            return SourceResult(name, url, 0, license_note, "skipped",
                                "no rows returned")
        n = _write_csv(OUT_DIR / out_file, rows, fieldnames)
        print(f"    wrote {n} rows -> data/raw/{out_file}")
        return SourceResult(name, url, n, license_note, "ok")
    except Exception as e:                          # noqa: BLE001
        print(f"    FAILED: {e!r}", file=sys.stderr)
        return SourceResult(name, url, 0, license_note, "error", repr(e))


# ---------------- individual fetchers ----------------

def fetch_jailbreakbench() -> list[dict]:
    """JailbreakBench harmful behaviors (HuggingFace).

    The dataset has a 'harmful' split with 100 behaviors, each labeled with
    a category. We treat all of these as label=1 (malicious) with
    attack_type='operational_request' as a default; the original dataset
    does not pre-classify by disguise type.
    """
    from datasets import load_dataset            # type: ignore
    ds = load_dataset("JailbreakBench/JBB-Behaviors", "behaviors", split="harmful")
    rows = []
    for r in ds:
        rows.append({
            "prompt": r.get("Goal") or r.get("goal") or r.get("Behavior") or "",
            "label": 1,
            "attack_type": "operational_request",
            "topic": (r.get("Category") or "unknown").lower().replace(" ", "_"),
            "source": "jailbreakbench",
        })
    # Drop empties
    rows = [r for r in rows if r["prompt"].strip()]
    return rows


def fetch_advbench() -> list[dict]:
    """AdvBench harmful behaviors from the original Zou et al. repo."""
    import urllib.request
    url = ("https://raw.githubusercontent.com/llm-attacks/llm-attacks/main/"
           "data/advbench/harmful_behaviors.csv")
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    reader = csv.DictReader(data.splitlines())
    rows = []
    for r in reader:
        prompt = (r.get("goal") or r.get("Goal") or "").strip()
        if not prompt:
            continue
        rows.append({
            "prompt": prompt,
            "label": 1,
            "attack_type": "operational_request",
            "topic": "advbench_harmful",
            "source": "advbench",
        })
    return rows


def fetch_hh_rlhf_helpful(max_rows: int = 3000) -> list[dict]:
    """Anthropic HH-RLHF helpful-base — extract just the *first human turn* as a
    benign prompt.  We cap at max_rows to keep dataset balanced."""
    from datasets import load_dataset            # type: ignore
    ds = load_dataset("Anthropic/hh-rlhf", data_dir="helpful-base", split="train")

    rows = []
    for r in ds:
        chosen = r.get("chosen", "")
        # Format is "\n\nHuman: ...\n\nAssistant: ..."
        marker = "Human:"
        if marker not in chosen:
            continue
        first = chosen.split(marker, 1)[1]
        # cut at next \n\nAssistant
        if "\n\nAssistant" in first:
            first = first.split("\n\nAssistant", 1)[0]
        prompt = first.strip()
        if 10 <= len(prompt) <= 600:
            rows.append({
                "prompt": prompt,
                "label": 0,
                "attack_type": "none",
                "topic": "hh_helpful",
                "source": "hh_rlhf_helpful_base",
            })
        if len(rows) >= max_rows:
            break
    return rows


def fetch_awesome_jailbreak() -> list[dict]:
    """A maintained list of jailbreak prompts (used widely in jailbreak literature).
    Source: https://github.com/verazuo/jailbreak_llms
    The repo includes a forbidden_question_set.csv with question + jailbreak combos."""
    import urllib.request
    # Use the public mirror of the dataset CSV
    url = ("https://raw.githubusercontent.com/verazuo/jailbreak_llms/main/"
           "data/forbidden_question/forbidden_question_set.csv")
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    reader = csv.DictReader(data.splitlines())
    rows = []
    for r in reader:
        prompt = (r.get("question") or "").strip()
        if not prompt:
            continue
        rows.append({
            "prompt": prompt,
            "label": 1,
            # These are baseline forbidden questions — mostly direct asks.
            # Once paired with the jailbreak prompt corpus they become disguised,
            # but the bare question itself is operational.
            "attack_type": "operational_request",
            "topic": (r.get("content_policy_name") or "forbidden").lower().replace(" ", "_"),
            "source": "verazuo_forbidden_questions",
        })
    return rows


# ---------------- main ----------------

def main():
    fieldnames = ["prompt", "label", "attack_type", "topic", "source"]
    results: list[SourceResult] = []

    results.append(_try(
        "JailbreakBench harmful behaviors",
        "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors",
        "MIT (verify on dataset card before publication).",
        fetch_jailbreakbench,
        "jailbreakbench.csv",
        fieldnames,
    ))

    results.append(_try(
        "AdvBench harmful behaviors",
        "https://github.com/llm-attacks/llm-attacks",
        "MIT (Zou et al., 2023). Cite the paper.",
        fetch_advbench,
        "advbench.csv",
        fieldnames,
    ))

    results.append(_try(
        "Anthropic HH-RLHF helpful-base (benign prompts)",
        "https://huggingface.co/datasets/Anthropic/hh-rlhf",
        "MIT. Anthropic-published; cite the HH paper.",
        lambda: fetch_hh_rlhf_helpful(max_rows=3000),
        "hh_helpful.csv",
        fieldnames,
    ))

    results.append(_try(
        "verazuo/jailbreak_llms forbidden-question set",
        "https://github.com/verazuo/jailbreak_llms",
        "Check repo LICENSE before publication. Used for academic research.",
        fetch_awesome_jailbreak,
        "verazuo_forbidden.csv",
        fieldnames,
    ))

    summary = {"sources": [asdict(r) for r in results]}
    with (OUT_DIR / "_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r.status:8s} {r.name:55s} rows={r.rows_written}")
    print(f"\nProvenance written to data/raw/_summary.json")


if __name__ == "__main__":
    main()
