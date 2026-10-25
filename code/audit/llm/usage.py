"""JSONL usage ledger (Phase 4 E4): one line per logical model request,
whether served by a real API call or a cache replay. `.cache/usage_
ledger.jsonl` (git-ignored; never part of code.zip). code/tools/
make_usage_report.py is the only reader.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402


def record(
    provider: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    latency_s: float = 0.0,
    cache_hit: bool = False,
    original_usage: dict | None = None,
    error: str = "",
) -> None:
    """Appends one ledger line. When `cache_hit` is True, input_tokens/
    output_tokens/thinking_tokens are the ORIGINAL call's usage (so the
    report can show the true token cost this request represents even
    though no new API call was made), and `original_usage` repeats them
    explicitly as its own field, per the Phase 4 task's required ledger
    shape."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "latency_s": round(latency_s, 3),
        "cache_hit": cache_hit,
        "original_usage": original_usage,
        "error": error,
    }
    config.USAGE_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.USAGE_LEDGER_PATH, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")


def read_all() -> list[dict]:
    if not config.USAGE_LEDGER_PATH.exists():
        return []
    entries = []
    with open(config.USAGE_LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries
