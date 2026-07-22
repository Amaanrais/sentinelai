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
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

RESULTS_DIR  = REPO_ROOT / "results"
PROBE_DATA   = REPO_ROOT / "probe_data" / "probe_data.csv"
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
        "model_id": "gemini-2.5-flash",
        "env_key":  "GOOGLE_API_KEY",
        # gemini-2.5-flash spends output tokens on hidden "thinking" before the
        # visible answer; at the default 512-token budget that left ~20 tokens
        # for the actual reply. Disabling thinking (supported on this model)
        # frees the whole budget for the answer.
        "thinking_budget": 0,
        # Google's free-tier API enforces a per-minute request cap. Throttle to
        # 5 requests/minute (>=12 s between request starts) to stay under it.
        "rpm": 5,
    },
    {
        "label":    "kimi-k2",
        "provider": "openai_compat",
        "model_id": "moonshotai/kimi-k2",
        "env_key":  "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        # OpenRouter throttles bursts and, under load, occasionally returns a
        # blank 200 from the upstream provider. Proactively space requests to
        # 10/minute (6 s apart) to reduce 429s; the retry layer recovers the
        # rest (429s honour Retry-After, blank responses are retried).
        "rpm": 10,
    },
    {
        "label":    "gemma-4",
        "provider": "google",
        "model_id": "gemma-4-31b-it",
        "env_key":  "GOOGLE_API_KEY",
        # Unlike gemini-2.5-flash, this model rejects thinking_config
        # ("Thinking budget is not supported for this model"), so thinking
        # can't be disabled. It reliably burns ~500-560 tokens on hidden
        # reasoning, so give it a floor well above that regardless of
        # --max-tokens, or the visible answer gets truncated to near-empty.
        "min_max_tokens": 2048,
        # Shares the Google per-minute request cap; throttle to 5 requests/min.
        "rpm": 5,
    },
]

CSV_FIELDS = [
    "prompt_id", "prompt", "label", "attack_type", "injection_vector",
    "surface_benignity", "obfuscation_method", "tier", "multi_turn_group",
    "model", "model_id", "response", "latency_s", "finish_reason", "error",
    "timestamp",
]


# ---------------------------------------------------------------------------
# Per-provider callers
# ---------------------------------------------------------------------------

# Per-request wall-clock cap so a hung upstream can't stall the whole run.
REQUEST_TIMEOUT_S = 60.0


class EmptyResponseError(RuntimeError):
    """A provider returned no usable text (empty choices or blank content).

    On OpenRouter this happens intermittently under load — the HTTP call is a
    200 but the upstream provider returned nothing. Treated as retryable so a
    transient blank doesn't get recorded as a permanent empty response.
    """


def _call_openai_sdk(
    model_id: str,
    prompt: str,
    api_key: str,
    max_tokens: int,
    base_url: str | None = None,
    extra_headers: dict | None = None,
) -> str:
    from openai import OpenAI
    kwargs: dict = {"api_key": api_key, "timeout": REQUEST_TIMEOUT_S, "max_retries": 0}
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
    if not resp.choices:
        raise EmptyResponseError(f"no choices returned (id={getattr(resp, 'id', None)})")
    content = resp.choices[0].message.content or ""
    if not content.strip():
        finish = resp.choices[0].finish_reason
        raise EmptyResponseError(f"blank content (finish_reason={finish})")
    return content


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


def _call_google(
    model_id: str,
    prompt: str,
    api_key: str,
    max_tokens: int,
    thinking_budget: int | None = None,
    min_max_tokens: int | None = None,
) -> tuple[str, str]:
    """Returns (text, finish_reason)."""
    from google import genai
    from google.genai import types
    # HttpOptions.timeout is in milliseconds. Without it a half-open connection
    # can hang the whole run indefinitely (the OpenAI path sets its own timeout).
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT_S * 1000)),
    )

    effective_max_tokens = max(max_tokens, min_max_tokens or 0)
    config_kwargs: dict = {
        "system_instruction": SYSTEM_PROMPT,
        "max_output_tokens": effective_max_tokens,
    }
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    finish_reason = ""
    if resp.candidates:
        fr = resp.candidates[0].finish_reason
        finish_reason = fr.name if fr is not None else ""
    return resp.text or "", finish_reason


def _dispatch(cfg: dict, prompt: str, max_tokens: int) -> tuple[str, str]:
    """Returns (text, finish_reason). finish_reason is '' for non-Google providers."""
    api_key  = os.environ[cfg["env_key"]]
    provider = cfg["provider"]
    model_id = cfg["model_id"]

    if provider == "openai":
        return _call_openai_sdk(model_id, prompt, api_key, max_tokens), ""

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
        ), ""

    if provider == "anthropic":
        return _call_anthropic(model_id, prompt, api_key, max_tokens), ""

    if provider == "google":
        return _call_google(
            model_id, prompt, api_key, max_tokens,
            thinking_budget=cfg.get("thinking_budget"),
            min_max_tokens=cfg.get("min_max_tokens"),
        )

    raise ValueError(f"Unknown provider: {provider}")


# HTTP statuses worth retrying: rate limit (429) and transient server errors.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
# openai-SDK exception class names that are transient regardless of status.
_RETRYABLE_EXC_NAMES = {
    "RateLimitError", "APITimeoutError", "APIConnectionError",
    "InternalServerError", "APIConnectionTimeoutError",
    # httpx / google-genai transport timeouts (Google path has no SDK retry)
    "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
    "TimeoutException", "ConnectError",
}


def _is_retryable(exc: Exception) -> bool:
    """True for transient failures worth another attempt; False for hard errors
    (e.g. 400 bad request, auth) so we don't burn the retry budget on them."""
    if isinstance(exc, EmptyResponseError):
        return True
    if getattr(exc, "status_code", None) in _RETRYABLE_STATUS:
        return True
    return type(exc).__name__ in _RETRYABLE_EXC_NAMES


def _retry_after_seconds(exc: Exception) -> float | None:
    """Honour a server-provided Retry-After header (seconds) when present."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _call_with_retry(cfg: dict, prompt: str, max_tokens: int, retries: int = 6) -> tuple[str, str, str]:
    """Returns (response, finish_reason, error). On success error is '', on failure response is ''.

    Retries transient failures (429s, 5xx, timeouts, blank OpenRouter responses)
    with jittered exponential backoff, honouring a Retry-After header when the
    server sends one. Non-retryable errors (bad request, auth) fail fast.
    """
    last_err = ""
    for attempt in range(retries):
        try:
            response, finish_reason = _dispatch(cfg, prompt, max_tokens)
            return response, finish_reason, ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt == retries - 1 or not _is_retryable(exc):
                break
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                delay = retry_after + random.uniform(0, 1)
            else:
                delay = min(2 ** attempt, 30) + random.uniform(0, 1)  # 1,2,4,8,16,30s + jitter
            time.sleep(delay)
    return "", "", last_err


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
    p.add_argument("--append", action="store_true",
                   help="Append rows to an existing CSV instead of creating a new file.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print first prompt per model without calling any API.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # --- Load dataset ---
    import csv as _csv
    print(f"Loading {PROBE_DATA}…")
    with open(PROBE_DATA, newline="", encoding="utf-8") as _fh:
        prompts: list[dict] = list(_csv.DictReader(_fh))
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
            print(f"[DRY RUN] {m['label']:12s} | {prompts[0]['prompt'][:100]}…")
        return

    # --- Run probes ---
    file_mode = "a" if args.append else "w"
    with open(out_path, file_mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not args.append:
            writer.writeheader()
        fh.flush()

        for model_cfg in active:
            # Minimum seconds between the *starts* of consecutive requests to
            # this model. Models with an "rpm" cap (e.g. Google's 5 req/min)
            # override the global --delay; everyone else uses --delay.
            rpm = model_cfg.get("rpm")
            min_interval = max(args.delay, 60.0 / rpm) if rpm else args.delay
            next_allowed = 0.0  # perf_counter timestamp of earliest next start

            for i, row in enumerate(
                tqdm(prompts, desc=f"{model_cfg['label']:12s}", unit="prompt", leave=True)
            ):
                # Throttle: don't start the next request until the interval has
                # elapsed since the previous request started. Time spent inside
                # the previous call counts toward the interval.
                wait = next_allowed - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)

                t0 = time.perf_counter()
                next_allowed = t0 + min_interval
                response, finish_reason, error = _call_with_retry(model_cfg, row["prompt"], args.max_tokens)
                latency = round(time.perf_counter() - t0, 3)

                writer.writerow({
                    "prompt_id":        row["id"],
                    "prompt":           row["prompt"],
                    "label":            row["label"],
                    "attack_type":      row["attack_type"],
                    "injection_vector": row["injection_vector"],
                    "surface_benignity":row["surface_benignity"],
                    "obfuscation_method":row["obfuscation_method"],
                    "tier":             row["tier"],
                    "multi_turn_group": row["multi_turn_group"],
                    "model":            model_cfg["label"],
                    "model_id":         model_cfg["model_id"],
                    "response":         response,
                    "latency_s":        latency,
                    "finish_reason":    finish_reason,
                    "error":            error,
                    "timestamp":        datetime.now(timezone.utc).isoformat(),
                })
                fh.flush()

    print(f"\nDone. {total_calls} rows written → {out_path}")


if __name__ == "__main__":
    main()
