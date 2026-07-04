"""
run_attack_type_confusion.py
----------------------------
Produces two per-attack-type confusion tables from already-computed reports.
No model inference is re-run.

Table A — In-distribution (dataset_v1_test.csv, 8 malicious attack types)
    Source: reports/{model}_report.json

Table B — Out-of-distribution (probe_data_v2.csv, 11 attack types)
    Source: reports/stratified/{model}_report.json

Outputs:
    reports/attack_type_confusion.md
    reports/attack_type_confusion.json
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
OUT_MD   = ROOT / "reports" / "attack_type_confusion.md"
OUT_JSON = ROOT / "reports" / "attack_type_confusion.json"

# --------------------------------------------------------------------------- #
# Report sources
# --------------------------------------------------------------------------- #

IN_DIST_REPORTS = {
    "DistilBERT": ROOT / "reports" / "distilbert_v1_report.json",
    "RoBERTa":    ROOT / "reports" / "roberta_v1_report.json",
    "TF-IDF+LR":  ROOT / "reports" / "baseline_tfidf_lr_report.json",
}

OOD_REPORTS = {
    "DistilBERT": ROOT / "reports" / "stratified" / "distilbert_v1_report.json",
    "RoBERTa":    ROOT / "reports" / "stratified" / "roberta_v1_report.json",
    "TF-IDF+LR":  ROOT / "reports" / "stratified" / "baseline_tfidf_report.json",
}

# Fixed display order for each table
IN_DIST_ORDER = [
    "injection",
    "jailbreak_explicit",
    "prompt_injection",
    "indirect_rag_injection",
    "fictional_framing",
    "authority_claim",
    "persona_jailbreak",
    "direct_harmful_request",
]

OOD_ORDER = [
    "persona_jailbreak",
    "indirect_rag_injection",
    "goal_hijacking",
    "authority_claim",
    "direct_harmful_request",
    "obfuscated_payload",
    "completion_hijack",
    "fictional_framing",
    "payload_splitting",
    "hypothetical_framing",
    "camouflaged_harmful",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cell(m: dict) -> tuple[int, int, float | None]:
    """Return (detected, total, recall) for a malicious attack-type group."""
    n   = m["positives"]
    rec = m["recall_on_positives"]
    det = round(rec * n) if rec is not None else 0
    return det, n, rec


def _fmt_cell(det: int, n: int, rec: float | None) -> str:
    if rec is None:
        return f"—/{n}"
    pct = f"{rec * 100:.1f}%"
    return f"{det}/{n} ({pct})"


def _fp_cell(m: dict) -> tuple[int, int, float | None]:
    """Return (FP, total_benign, specificity) for the benign group."""
    neg  = m["negatives"]
    spec = m["specificity_on_negatives"]
    tn   = round(spec * neg) if spec is not None else neg
    fp   = neg - tn
    return fp, neg, spec


# --------------------------------------------------------------------------- #
# Table builders
# --------------------------------------------------------------------------- #

def build_table_a(reports: dict[str, dict]) -> tuple[str, dict]:
    """In-distribution: malicious rows + one benign FP row."""
    model_names = list(reports.keys())
    header = (
        "| Attack type | n |"
        + "".join(f" {m} |" for m in model_names)
    )
    sep = (
        "|---|---:|"
        + "|".join(["---:"] * len(model_names))
        + "|"
    )
    lines = [header, sep]

    data_out: dict[str, dict] = {}

    for atype in IN_DIST_ORDER:
        row_data: dict[str, dict] = {}
        cells = []
        n_ref = None
        for mname, report in reports.items():
            pat = report["per_attack_type"]
            if atype not in pat:
                cells.append("—")
                continue
            m   = pat[atype]
            det, n, rec = _cell(m)
            n_ref = n
            cells.append(_fmt_cell(det, n, rec))
            row_data[mname] = {"detected": det, "total": n, "recall": rec}

        n_str = str(n_ref) if n_ref is not None else "—"
        lines.append("| " + atype + " | " + n_str + " | " + " | ".join(cells) + " |")
        data_out[atype] = row_data

    # Benign FP row — sourced from "none" group
    fp_cells = []
    fp_data: dict[str, dict] = {}
    for mname, report in reports.items():
        pat = report["per_attack_type"]
        if "none" not in pat:
            fp_cells.append("—")
            continue
        m = pat["none"]
        fp, neg, spec = _fp_cell(m)
        fp_cells.append(f"{fp} FP / {neg} ({spec * 100:.1f}% spec)" if spec is not None else "—")
        fp_data[mname] = {"false_positives": fp, "total_benign": neg, "specificity": spec}

    lines.append("| **none (benign)** | 225 | " + " | ".join(fp_cells) + " |")
    data_out["none_benign"] = fp_data

    return "\n".join(lines), data_out


def build_table_b(reports: dict[str, dict]) -> tuple[str, dict]:
    """Out-of-distribution: malicious rows only (no benign samples in probe_data_v2)."""
    model_names = list(reports.keys())
    header = (
        "| Attack type | n |"
        + "".join(f" {m} |" for m in model_names)
    )
    sep = (
        "|---|---:|"
        + "|".join(["---:"] * len(model_names))
        + "|"
    )
    lines = [header, sep]

    data_out: dict[str, dict] = {}

    for atype in OOD_ORDER:
        row_data: dict[str, dict] = {}
        cells = []
        n_ref = None
        for mname, report in reports.items():
            pat = report["per_attack_type"]
            if atype not in pat:
                cells.append("—")
                continue
            m   = pat[atype]
            det, n, rec = _cell(m)
            n_ref = n
            cells.append(_fmt_cell(det, n, rec))
            row_data[mname] = {"detected": det, "total": n, "recall": rec}

        n_str = str(n_ref) if n_ref is not None else "—"
        lines.append("| " + atype + " | " + n_str + " | " + " | ".join(cells) + " |")
        data_out[atype] = row_data

    return "\n".join(lines), data_out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    # Load reports
    in_dist = {name: _load(path) for name, path in IN_DIST_REPORTS.items()}
    ood     = {name: _load(path) for name, path in OOD_REPORTS.items()}

    table_a_md, table_a_data = build_table_a(in_dist)
    table_b_md, table_b_data = build_table_b(ood)

    # Markdown output
    md_lines = [
        "# Per-attack-type detection — cross-model comparison\n",

        "## Table A — In-distribution (dataset_v1_test, n=450)\n",
        "Prompts drawn from the same seven sources used for training.",
        "Cell format: `detected / total (recall%)`\n",
        table_a_md,

        "\n## Table B — Out-of-distribution (probe_data_v2, n=440)\n",
        "Novel GPT-generated prompts, none seen during training.",
        "All samples are malicious (no benign baseline for this table).",
        "Cell format: `detected / total (recall%)`\n",
        table_b_md,
    ]
    md = "\n".join(md_lines)

    OUT_MD.write_text(md, encoding="utf-8")
    print(md)

    # JSON output
    payload = {
        "table_a_in_distribution": {
            "source": "dataset_v1_test.csv",
            "n": 450,
            "results": table_a_data,
        },
        "table_b_out_of_distribution": {
            "source": "probe_data_v2.csv",
            "n": 440,
            "results": table_b_data,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n[ok] {OUT_MD}")
    print(f"[ok] {OUT_JSON}")


if __name__ == "__main__":
    main()
