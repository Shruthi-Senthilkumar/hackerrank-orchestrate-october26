"""Capability probe (script, not a pytest test).

Phase 1 carry-over task 0c. Answers two yes/no questions empirically,
against the live provider APIs, instead of trusting documentation:

1. Does Groq qwen/qwen3.8-27b accept a strict JSON-schema response format,
   and can "thinking" be turned off (reasoning_effort="none"), while still
   producing a valid object that matches the schema?
2. Does Gemini gemini-3.1-flash-lite accept a response schema together with
   a small locally generated image input (a few KB), and what do its usage
   fields (thoughts_token_count, total_token_count) report? Only
   gemini-3.1-flash-lite is called here; gemini-3.8-flash is never called
   in Phase 1 (it is rare/budgeted, see DECISIONS.md D9, D11).

Prints only yes/no answers and token counts. Never prints keys or full
response bodies. Hard per-call timeout of 90 seconds, at most one retry.

Usage: python code/tests/probe_capabilities.py
"""

import io
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"
sys.path.insert(0, str(CODE_DIR))

import config  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

TIMEOUT_S = 90
MAX_RETRIES = 1

GROQ_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

GEMINI_SCHEMA = {
    "type": "object",
    "properties": {"color": {"type": "string"}},
    "required": ["color"],
}


def _make_tiny_png_bytes() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def probe_groq_structured_output() -> None:
    import json as _json

    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=TIMEOUT_S)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=config.INTENT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": "What color is the sky on a clear day? "
                        'Respond as JSON: {"answer": "<color>"}',
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "probe_schema",
                        "schema": GROQ_SCHEMA,
                        "strict": True,
                    },
                },
                reasoning_effort="none",
                max_completion_tokens=50,
                temperature=0,
            )
            content = resp.choices[0].message.content
            parsed = _json.loads(content)
            schema_ok = isinstance(parsed, dict) and "answer" in parsed
            reasoning_content = getattr(resp.choices[0].message, "reasoning", None)
            thinking_off_ok = not reasoning_content
            print(f"groq_json_schema_accepted: {'yes' if schema_ok else 'no'}")
            print(f"groq_thinking_off_accepted: {'yes' if thinking_off_ok else 'no (reasoning field present)'}")
            print(
                f"groq_valid_object_produced: {'yes' if schema_ok else 'no'} "
                f"input_tokens={resp.usage.prompt_tokens} output_tokens={resp.usage.completion_tokens}"
            )
            return
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
    print(f"groq_json_schema_accepted: no (error_class={type(last_error).__name__})")
    print("groq_thinking_off_accepted: no (call failed)")
    print("groq_valid_object_produced: no (call failed)")


def probe_gemini_schema_with_image() -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000),
    )
    image_bytes = _make_tiny_png_bytes()

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model=config.EXTRACT_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    "What is the dominant color of this image? Answer the schema.",
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GEMINI_SCHEMA,
                    thinking_config=types.ThinkingConfig(include_thoughts=False),
                ),
            )
            import json as _json

            parsed = _json.loads(resp.text)
            schema_ok = isinstance(parsed, dict) and "color" in parsed
            usage = resp.usage_metadata
            print(f"gemini_schema_with_image_accepted: {'yes' if schema_ok else 'no'}")
            print(
                f"gemini_usage: prompt_tokens={usage.prompt_token_count} "
                f"candidates_tokens={usage.candidates_token_count} "
                f"thoughts_tokens={usage.thoughts_token_count} "
                f"total_tokens={usage.total_token_count}"
            )
            return
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
    print(f"gemini_schema_with_image_accepted: no (error_class={type(last_error).__name__})")
    print("gemini_usage: n/a (call failed)")


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    print(f"--- Groq probe: model={config.INTENT_MODEL} ---")
    probe_groq_structured_output()
    print(f"--- Gemini probe: model={config.EXTRACT_MODEL} (flash-lite only; flash never called) ---")
    probe_gemini_schema_with_image()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
