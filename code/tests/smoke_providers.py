"""Provider connectivity smoke tests (script, not a pytest test).

Makes one tiny Groq call and one tiny Gemini call and prints only:
provider, model ID, "ok" or the error class plus HTTP status, input
tokens, output tokens, latency. Never prints keys or response bodies.

Phase 0 note: the PRD's intent model (qwen/qwen3-32b) and its comparison
model (qwen/qwen3.6-27b) are not available on this Groq key. The user
confirmed qwen/qwen3.8-27b as the replacement (see code/config.py and
log.txt); this script smoke-tests that confirmed model.

Usage: python code/tests/smoke_providers.py
"""

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"
sys.path.insert(0, str(CODE_DIR))

import config  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

GROQ_SMOKE_MODEL = config.INTENT_MODEL
GEMINI_SMOKE_MODEL = config.EXTRACT_MODEL


def smoke_groq() -> None:
    provider = "groq"
    model = GROQ_SMOKE_MODEL
    start = time.monotonic()
    try:
        from groq import Groq

        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=5,
            temperature=0,
        )
        latency = time.monotonic() - start
        usage = resp.usage
        print(
            f"provider={provider} model={model} result=ok "
            f"input_tokens={usage.prompt_tokens} output_tokens={usage.completion_tokens} "
            f"latency_s={latency:.2f}"
        )
    except Exception as e:
        latency = time.monotonic() - start
        status = getattr(e, "status_code", "n/a")
        print(
            f"provider={provider} model={model} result=error "
            f"error_class={type(e).__name__} http_status={status} latency_s={latency:.2f}"
        )


def smoke_gemini() -> None:
    provider = "gemini"
    model = GEMINI_SMOKE_MODEL
    start = time.monotonic()
    try:
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=model,
            contents="Reply with exactly: ok",
        )
        latency = time.monotonic() - start
        usage = resp.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", "n/a")
        output_tokens = getattr(usage, "candidates_token_count", "n/a")
        print(
            f"provider={provider} model={model} result=ok "
            f"input_tokens={input_tokens} output_tokens={output_tokens} "
            f"latency_s={latency:.2f}"
        )
    except Exception as e:
        latency = time.monotonic() - start
        status = getattr(e, "status_code", "n/a")
        print(
            f"provider={provider} model={model} result=error "
            f"error_class={type(e).__name__} http_status={status} latency_s={latency:.2f}"
        )


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    smoke_groq()
    smoke_gemini()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
