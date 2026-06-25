"""
probe_models.py
---------------
Queries 7 AI models with the 100 harmful prompts from JailbreakBench/JBB-Behaviors
and writes one CSV row per (prompt × model) pair to results/.

Usage:
    python scripts/probe_models.py
    python scripts/probe_models.py --models openai anthropic --dry-run
    python scripts/probe_models.py --delay 2 --max-tokens 256
    python scripts/probe_models.py --output path/to/custom.csv

Required: populate .env in the repo root with API keys (see .env.example).
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from datasets import load_dataset
from dotenv import load_dotenv
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

RESULTS_DIR = REPO_ROOT / "results"
SYSTEM_PROMPT = "You are a helpful assistant."

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
# provider values:
#   "openai"        → OpenAI Python SDK, openai.com endpoint
#   "openai_compat" → OpenAI Python SDK, third-party base_url
#   "anthropic"     → Anthropic Python SDK
#   "google"        → google-generativeai SDK (Gemini + Gemma-3 share the same key)
ALL_MODELS: list[dict] = [
    {
        "label":    "openai",
        "provider": "openai",
        "model_id": "gpt-4o",
        "env_key":  "OPENAI_API_KEY",
    },
    {
        "label":    "gemini",
        "provider": "google",
        "model_id": "gemini-1.5-pro",
        "env_key":  "GOOGLE_API_KEY",
    },
    {
        "label":    "anthropic",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "env_key":  "ANTHROPIC_API_KEY",
    },
    {
        "label":    "deepseek",
        "provider": "openai_compat",
        "model_id": "deepseek-chat",
        "env_key":  "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
    },
    {
        "label":    "kimi-k2",
        "provider": "openai_compat",
        "model_id": "moonshotai/kimi-k2",
        "env_key":  "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "label":    "gemma-3",
        "provider": "google",
        "model_id": "gemma-3-27b-it",
        "env_key":  "GOOGLE_API_KEY",
    },
]

CSV_FIELDS = [
    "prompt_id", "behavior", "category", "source",
    "goal", "model", "model_id", "response", "latency_s", "error", "timestamp",
]


# ---------------------------------------------------------------------------
# Per-provider callers
# ---------------------------------------------------------------------------

def _call_openai_sdk(
    model_id: str,
    prompt: str,
    api_key: str,
    max_tokens: int,
    base_url: str | None = None,
    extra_headers: dict | None = None,
) -> str:
    from openai import OpenAI
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if extra_headers:
        kwargs["default_headers"] = extra_headers
    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(model_id: str, prompt: str, api_key: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _call_google(model_id: str, prompt: str, api_key: str, max_tokens: int) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_id,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
    )
    resp = model.generate_content(prompt)
    return resp.text


def _dispatch(cfg: dict, prompt: str, max_tokens: int) -> str:
    api_key  = os.environ[cfg["env_key"]]
    provider = cfg["provider"]
    model_id = cfg["model_id"]

    if provider == "openai":
        return _call_openai_sdk(model_id, prompt, api_key, max_tokens)

    if provider == "openai_compat":
        # OpenRouter requires identifying headers for better rate limits
        headers = (
            {"HTTP-Referer": "sentinelai-probe", "X-Title": "SentinelAI"}
            if "openrouter" in cfg.get("base_url", "")
            else None
        )
        return _call_openai_sdk(
            model_id, prompt, api_key, max_tokens,
            base_url=cfg["base_url"], extra_headers=headers,
        )

    if provider == "anthropic":
        return _call_anthropic(model_id, prompt, api_key, max_tokens)

    if provider == "google":
        return _call_google(model_id, prompt, api_key, max_tokens)

    raise ValueError(f"Unknown provider: {provider}")


def _call_with_retry(cfg: dict, prompt: str, max_tokens: int, retries: int = 3) -> tuple[str, str]:
    """Returns (response, error). On success error is '', on failure response is ''."""
    last_err = ""
    for attempt in range(retries):
        try:
            return _dispatch(cfg, prompt, max_tokens), ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))  # 2 s, then 4 s
    return "", last_err


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    label_choices = [m["label"] for m in ALL_MODELS]
    p = argparse.ArgumentParser(
        description="Probe multiple LLMs with JailbreakBench harmful prompts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--models", nargs="+", default=["all"],
        choices=label_choices + ["all"], metavar="MODEL",
        help=f"Models to query. One or more of: {label_choices + ['all']}.",
    )
    p.add_argument("--max-tokens", type=int, default=512,
                   help="Max tokens per response.")
    p.add_argument("--delay", type=float, default=1.0,
                   help="Seconds to wait between calls to the same model.")
    p.add_argument("--output", type=str, default=None,
                   help="Output CSV path. Defaults to results/probe_results_<timestamp>.csv.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print first prompt per model without calling any API.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # --- Load dataset ---
    print("Loading JailbreakBench/JBB-Behaviors (harmful split)…")
    ds = load_dataset("JailbreakBench/JBB-Behaviors", "behaviors", split="harmful")
    prompts: list[dict] = list(ds)
    print(f"  {len(prompts)} prompts loaded.\n")

    # --- Select and validate models ---
    if "all" in args.models:
        selected = ALL_MODELS[:]
    else:
        label_set = set(args.models)
        selected = [m for m in ALL_MODELS if m["label"] in label_set]

    active: list[dict] = []
    for m in selected:
        if os.environ.get(m["env_key"]):
            active.append(m)
        else:
            print(f"[SKIP] {m['label']:12s} — {m['env_key']} not set in .env")

    if not active:
        print("\nNo models available. Populate .env and retry.")
        return

    # --- Resolve output path ---
    RESULTS_DIR.mkdir(exist_ok=True)
    if args.output:
        out_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"probe_results_{ts}.csv"

    total_calls = len(active) * len(prompts)
    print(f"Models : {[m['label'] for m in active]}")
    print(f"Prompts: {len(prompts)}")
    print(f"Calls  : {total_calls}")
    print(f"Output : {out_path}\n")

    if args.dry_run:
        for m in active:
            print(f"[DRY RUN] {m['label']:12s} | {prompts[0]['Goal'][:100]}…")
        return

    # --- Run probes ---
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        fh.flush()

        for model_cfg in active:
            for i, row in enumerate(
                tqdm(prompts, desc=f"{model_cfg['label']:12s}", unit="prompt", leave=True)
            ):
                t0 = time.perf_counter()
                response, error = _call_with_retry(model_cfg, row["Goal"], args.max_tokens)
                latency = round(time.perf_counter() - t0, 3)

                writer.writerow({
                    "prompt_id": row["Index"],
                    "behavior":  row["Behavior"],
                    "category":  row["Category"],
                    "source":    row["Source"],
                    "goal":      row["Goal"],
                    "model":     model_cfg["label"],
                    "model_id":  model_cfg["model_id"],
                    "response":  response,
                    "latency_s": latency,
                    "error":     error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                fh.flush()

                # Delay between calls, but not after the last prompt for this model
                if args.delay > 0 and i < len(prompts) - 1:
                    time.sleep(args.delay)

    print(f"\nDone. {total_calls} rows written → {out_path}")


if __name__ == "__main__":
    main()
