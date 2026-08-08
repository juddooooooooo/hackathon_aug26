"""
Shared Gemini client wrapper used by every Gen AI component in this pipeline
(Phase 2 forensic extraction, Phase 3 financial-statement extraction, and the
Phase 8 briefing notes). Centralises the three things that get scored
directly against the brief's Gen AI criterion:

  1. Prompt logging  -> prompts/<namespace>/*.json (evidence of the workflow)
  2. Response caching -> cache/<namespace>/*.json (reruns are free; keyed by
     a hash of the *full* input, not just the memo string -- see docstring
     on generate_structured for why)
  3. A per-call usage ledger -> reports/llm_usage_log.jsonl (latency + token
     counts for every call, hit or miss) feeding the Phase 7 cost/latency
     before/after chart.

No call site should touch the google.genai SDK directly -- go through
generate_structured() so every LLM call in the codebase is logged the same way.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Type, TypeVar

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.common import CACHE_DIR, PROMPTS_DIR, REPORTS_DIR, ROOT, ensure_dirs

logger = logging.getLogger(__name__)

load_dotenv(ROOT / ".env")

# Model routing. MODEL_DEFAULT does the real extraction work in Phases 2-3.
# MODEL_SMALL exists for Phase 7's latency/cost routing experiment (cheap
# model for easy classification, escalate to the bigger model only for hard
# cases). Override via env var if a model id is ever renamed/retired.
MODEL_DEFAULT = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MODEL_SMALL = os.environ.get("GEMINI_MODEL_SMALL", "gemini-2.5-flash-lite")

_client: Optional[genai.Client] = None
T = TypeVar("T", bound=BaseModel)


class MissingAPIKeyError(RuntimeError):
    """Raised when no Gemini API key is configured. See .env.example."""


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise MissingAPIKeyError(
                "No GEMINI_API_KEY (or GOOGLE_API_KEY) found in the environment or .env file.\n"
                f"Create {ROOT / '.env'} with:\n  GEMINI_API_KEY=your-key-here\n"
                "(see .env.example)."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def _hash_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _cache_path(namespace: str, key: str) -> Path:
    d = CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _is_retryable(exc: BaseException) -> bool:
    # Retry on rate limiting, transient server errors, and transport-level
    # connection failures (google-genai has its own internal retry for
    # these, but it doesn't always exhaust the same errors we see here --
    # observed ~0.5% of a 4,199-row run failing on a bare httpx.ReadError /
    # WinError 10054 with no retry at all). Anything else (bad request,
    # schema mismatch, auth failure) should fail immediately and visibly
    # rather than burn 5 attempts on a deterministic error.
    if isinstance(exc, APIError):
        return getattr(exc, "code", None) in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))


@dataclass
class LLMResult:
    parsed: Optional[BaseModel]
    raw_text: str
    cached: bool
    latency_ms: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    model: str


def _usage_log_path() -> Path:
    return REPORTS_DIR / "llm_usage_log.jsonl"


def _append_usage_log(entry: dict) -> None:
    ensure_dirs()
    with open(_usage_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _call_gemini(
    model: str, system_instruction: str, prompt: str, response_schema: Type[T], temperature: float
):
    client = get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=temperature,
        # Structured classification over a couple of short sentences doesn't
        # need extended reasoning; keep latency/cost down (also makes the
        # Phase 7 "before" baseline honest rather than artificially slow).
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    t0 = time.perf_counter()
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    latency_ms = (time.perf_counter() - t0) * 1000
    return response, latency_ms


def generate_structured(
    *,
    namespace: str,
    system_instruction: str,
    prompt: str,
    response_schema: Type[T],
    model: str = MODEL_DEFAULT,
    temperature: float = 0.0,
    use_cache: bool = True,
    log_prompts: bool = True,
    extra_cache_key: str = "",
) -> LLMResult:
    """Call Gemini with a strict JSON schema; cache + log every call.

    The cache/log key hashes (model, system_instruction, prompt,
    extra_cache_key) -- deliberately NOT the memo text alone. Phase 2 feeds
    the model memo + beneficiary_name jointly (memo text alone never names a
    lender in this dataset -- see METHODOLOGY.md), so a memo-only hash would
    silently collide two different beneficiaries sharing the same templated
    memo string. `extra_cache_key` lets each call site fold in exactly the
    extra context that can change the answer.
    """
    key = _hash_key(model, system_instruction, prompt, extra_cache_key)
    cache_file = _cache_path(namespace, key)

    if use_cache and cache_file.exists():
        cached_payload = json.loads(cache_file.read_text(encoding="utf-8"))
        parsed = (
            response_schema.model_validate(cached_payload["parsed"])
            if cached_payload.get("parsed") is not None
            else None
        )
        result = LLMResult(
            parsed=parsed,
            raw_text=cached_payload["raw_text"],
            cached=True,
            latency_ms=0.0,
            input_tokens=cached_payload.get("input_tokens"),
            output_tokens=cached_payload.get("output_tokens"),
            model=model,
        )
        _append_usage_log(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "namespace": namespace,
                "key": key,
                "model": model,
                "cached": True,
                "latency_ms": 0.0,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        )
        return result

    response, latency_ms = _call_gemini(model, system_instruction, prompt, response_schema, temperature)
    parsed = response.parsed
    usage = response.usage_metadata
    input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage else None

    payload = {
        "parsed": parsed.model_dump() if parsed is not None else None,
        "raw_text": response.text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if use_cache:
        cache_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    if log_prompts:
        ensure_dirs()
        log_dir = PROMPTS_DIR / namespace
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
        log_file = log_dir / f"{ts}__{key[:12]}.json"
        log_file.write_text(
            json.dumps(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "namespace": namespace,
                    "model": model,
                    "temperature": temperature,
                    "system_instruction": system_instruction,
                    "prompt": prompt,
                    "response_schema": response_schema.__name__,
                    "raw_response": response.text,
                    "parsed": payload["parsed"],
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": round(latency_ms, 1),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    _append_usage_log(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "namespace": namespace,
            "key": key,
            "model": model,
            "cached": False,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    )

    return LLMResult(
        parsed=parsed,
        raw_text=response.text,
        cached=False,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
