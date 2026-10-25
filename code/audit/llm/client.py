"""One client module for every model call in the pipeline (Phase 4
F13, F05, E4). C1: models only extract/classify; every call here
returns a validated JSON object, never a decision. C10: the API keys
are read from the environment once, here, and never logged or
returned to any caller.

Call flow for every request (intent or vision):
1. Build the cache key from the (normalized) input + model id + prompt
   version.
2. Cache hit -> return it (cache_hit=True in the ledger, zero network).
3. Cache miss and `ai_enabled=False` (a `--no-ai` run) -> raise
   AIDisabledError. A `--no-ai` run must never reach the network.
4. Cache miss and `ai_enabled=True` -> rate-limit, call, validate
   against the strict schema (reject, never repair, on failure),
   record to the ledger, cache, return.
"""

import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Optional

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402
from audit.llm import cache, limiter, usage  # noqa: E402
from audit.llm.schemas import INTENT_BATCH_RESPONSE_SCHEMA, INTENT_RESULT_SCHEMA, vision_schema  # noqa: E402


class AIDisabledError(RuntimeError):
    """Raised when a model call would be needed but ai_enabled=False
    (a `--no-ai` run) and there is no cached result for it."""


class ModelOutputInvalid(RuntimeError):
    """Raised when a model's JSON output fails strict schema
    validation. Never repaired by guessing (C3) -- the caller decides
    the safe fallback."""


_EXECUTOR = ThreadPoolExecutor(max_workers=4)

_groq_bucket = limiter.TokenBucket(config.GROQ_REQUESTS_PER_MINUTE, config.GROQ_TOKENS_PER_MINUTE)
_gemini_bucket = limiter.TokenBucket(config.GEMINI_REQUESTS_PER_MINUTE, config.GEMINI_TOKENS_PER_MINUTE)
_gemini_flash_daily = limiter.DailyBudget(config.EXTRACT_MODEL_RARE, config.GEMINI_FLASH_REQUESTS_PER_DAY)

_groq_client = None
_gemini_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        _gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_client


def _with_timeout(fn, *args, timeout_s: float = config.LLM_CALL_TIMEOUT_S, **kwargs):
    future = _EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeoutError as e:
        raise TimeoutError(f"model call exceeded {timeout_s}s") from e


def _retry_with_backoff(fn, retry_cap: int = config.LLM_RETRY_CAP):
    """Runs fn() with exponential backoff + jitter on 429/5xx-shaped
    errors and timeouts, capped at `retry_cap` retries (so at most
    retry_cap + 1 total attempts)."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            status = getattr(e, "status_code", None)
            is_retryable = isinstance(e, TimeoutError) or status in (429, 500, 502, 503, 504)
            if not is_retryable or attempt >= retry_cap:
                raise
            delay = (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)
            attempt += 1


def _json_extract(text: str) -> dict:
    """Models are told to return ONLY a JSON object; still strip any
    accidental markdown code fence before parsing, since a wrapped
    fence is a formatting slip, not a content decision."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Intent (F13)
# ---------------------------------------------------------------------------


def _groq_call(messages: list[dict], model: str, max_tokens: int) -> tuple[dict, dict, float]:
    def do_call():
        client = _get_groq_client()
        start = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0,
            response_format={"type": "json_object"},
            reasoning_effort="none",
        )
        latency = time.monotonic() - start
        parsed = _json_extract(resp.choices[0].message.content)
        usage_dict = {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
            "thinking_tokens": 0,
        }
        return parsed, usage_dict, latency

    _groq_bucket.acquire(max_tokens)
    return _retry_with_backoff(lambda: _with_timeout(do_call))


def intent_classify_batch(texts: list[str], ai_enabled: bool, system_prompt: str) -> list[dict]:
    """One Groq call classifying up to len(texts) request texts (the
    caller batches into groups of config.INTENT_BATCH_SIZE). Returns
    one validated result dict per input text, in the SAME order,
    aligned by the `id` field the model is asked to echo back."""
    model = config.INTENT_MODEL
    normalized = "\x1e".join(texts)  # record-separator; never appears in request text
    key = cache.cache_key(normalized.encode("utf-8"), model, config.INTENT_PROMPT_VERSION)
    cached = cache.get(key)
    if cached is not None:
        usage.record(
            provider="groq", model=model, prompt_version=config.INTENT_PROMPT_VERSION,
            input_tokens=cached["usage"]["input_tokens"], output_tokens=cached["usage"]["output_tokens"],
            thinking_tokens=cached["usage"].get("thinking_tokens", 0), latency_s=0.0, cache_hit=True,
            original_usage=cached["usage"],
        )
        return cached["results"]

    if not ai_enabled:
        raise AIDisabledError(f"intent batch of {len(texts)} texts needs a live Groq call but ai_enabled=False")

    batch_input = {"items": [{"id": i, "text": t} for i, t in enumerate(texts)]}
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(batch_input, ensure_ascii=False)},
    ]
    parsed, usage_dict, latency = _groq_call(messages, model, max_tokens=config.MAX_TOKENS_PER_CALL)
    jsonschema.validate(parsed, INTENT_BATCH_RESPONSE_SCHEMA)
    by_id = {r["id"]: r for r in parsed["results"]}
    results = []
    for i in range(len(texts)):
        r = by_id.get(i)
        if r is None:
            raise ModelOutputInvalid(f"batch response missing id {i}")
        item = {"intent": r["intent"], "language": r["language"], "evidence_phrase": r["evidence_phrase"]}
        jsonschema.validate(item, INTENT_RESULT_SCHEMA)
        results.append(item)

    usage.record(
        provider="groq", model=model, prompt_version=config.INTENT_PROMPT_VERSION,
        input_tokens=usage_dict["input_tokens"], output_tokens=usage_dict["output_tokens"],
        thinking_tokens=usage_dict["thinking_tokens"], latency_s=latency, cache_hit=False,
    )
    cache.put(key, {"results": results, "usage": usage_dict})
    return results


def intent_classify_single(text: str, ai_enabled: bool, system_prompt: str) -> dict:
    model = config.INTENT_MODEL
    key = cache.cache_key(text.encode("utf-8"), model, config.INTENT_PROMPT_VERSION + "-single")
    cached = cache.get(key)
    if cached is not None:
        usage.record(
            provider="groq", model=model, prompt_version=config.INTENT_PROMPT_VERSION,
            input_tokens=cached["usage"]["input_tokens"], output_tokens=cached["usage"]["output_tokens"],
            thinking_tokens=cached["usage"].get("thinking_tokens", 0), latency_s=0.0, cache_hit=True,
            original_usage=cached["usage"],
        )
        return cached["result"]

    if not ai_enabled:
        raise AIDisabledError("single-text intent escalation needs a live Groq call but ai_enabled=False")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({"items": [{"id": 0, "text": text}]}, ensure_ascii=False)},
    ]
    parsed, usage_dict, latency = _groq_call(messages, model, max_tokens=config.MAX_TOKENS_PER_CALL)
    jsonschema.validate(parsed, INTENT_BATCH_RESPONSE_SCHEMA)
    r = next((x for x in parsed["results"] if x["id"] == 0), None)
    if r is None:
        raise ModelOutputInvalid("single-text response missing id 0")
    result = {"intent": r["intent"], "language": r["language"], "evidence_phrase": r["evidence_phrase"]}
    jsonschema.validate(result, INTENT_RESULT_SCHEMA)

    usage.record(
        provider="groq", model=model, prompt_version=config.INTENT_PROMPT_VERSION,
        input_tokens=usage_dict["input_tokens"], output_tokens=usage_dict["output_tokens"],
        thinking_tokens=usage_dict["thinking_tokens"], latency_s=latency, cache_hit=False,
    )
    cache.put(key, {"result": result, "usage": usage_dict})
    return result


# ---------------------------------------------------------------------------
# Vision (F05)
# ---------------------------------------------------------------------------


def _gemini_call(prompt: str, image_bytes: bytes, mime_type: str, model: str, schema: dict) -> tuple[dict, dict, float]:
    def do_call():
        from google.genai import types

        client = _get_gemini_client()
        start = time.monotonic()
        resp = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        types.Part.from_text(text=prompt),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                max_output_tokens=config.MAX_TOKENS_PER_CALL,
            ),
        )
        latency = time.monotonic() - start
        parsed = _json_extract(resp.text)
        u = resp.usage_metadata
        usage_dict = {
            "input_tokens": getattr(u, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(u, "candidates_token_count", 0) or 0,
            "thinking_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        }
        return parsed, usage_dict, latency

    _gemini_bucket.acquire(config.MAX_TOKENS_PER_CALL)
    return _retry_with_backoff(lambda: _with_timeout(do_call))


def extract_image_facts(
    image_bytes: bytes,
    mime_type: str,
    model: str,
    system_ids: list[str],
    ai_enabled: bool,
    prompt: str,
) -> Optional[dict]:
    """Returns a validated facts dict, or None if the model is
    unavailable (budget exhausted for a rare/budgeted model, or
    AIDisabledError with no cache -- both are reported by the caller
    as "model unavailable", never guessed at)."""
    key = cache.cache_key(image_bytes, model, config.VISION_PROMPT_VERSION)
    cached = cache.get(key)
    if cached is not None:
        usage.record(
            provider="gemini", model=model, prompt_version=config.VISION_PROMPT_VERSION,
            input_tokens=cached["usage"]["input_tokens"], output_tokens=cached["usage"]["output_tokens"],
            thinking_tokens=cached["usage"].get("thinking_tokens", 0), latency_s=0.0, cache_hit=True,
            original_usage=cached["usage"],
        )
        return cached["result"]

    if not ai_enabled:
        raise AIDisabledError(f"image extraction with {model} needs a live Gemini call but ai_enabled=False")

    if model == config.EXTRACT_MODEL_RARE:
        if not _gemini_flash_daily.consume(1):
            return None  # daily budget exhausted; caller treats this as "model unavailable"

    schema = vision_schema(system_ids)
    full_prompt = f"{prompt}\n\nRespond with ONLY a JSON object matching this schema:\n{json.dumps(schema)}"
    try:
        parsed, usage_dict, latency = _gemini_call(full_prompt, image_bytes, mime_type, model, schema)
    except Exception as e:
        usage.record(
            provider="gemini", model=model, prompt_version=config.VISION_PROMPT_VERSION,
            input_tokens=0, output_tokens=0, latency_s=0.0, cache_hit=False, error=str(type(e).__name__),
        )
        raise

    jsonschema.validate(parsed, schema)
    usage.record(
        provider="gemini", model=model, prompt_version=config.VISION_PROMPT_VERSION,
        input_tokens=usage_dict["input_tokens"], output_tokens=usage_dict["output_tokens"],
        thinking_tokens=usage_dict["thinking_tokens"], latency_s=latency, cache_hit=False,
    )
    cache.put(key, {"result": parsed, "usage": usage_dict})
    return parsed
