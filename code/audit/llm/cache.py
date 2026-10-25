"""Content-addressed cache for model results (Phase 4 F13/F05, E4).

Every model call is cached by SHA-256 of (normalized input bytes + model
id + prompt version). A cache hit means `--no-ai` and a warm second run
make zero model calls, per the Phase 4 task's own exit criterion. Cache
entries live under `.cache/llm_cache/` (git-ignored; never part of the
submission's code.zip, never read by audit logic outside this module).

For intent, the cache key's input is the normalized request text. For
image/PDF extraction, the input is the file's own bytes -- callers pass
whatever bytes should distinguish two calls; this module never cares
which.
"""

import hashlib
import json
import sys
from pathlib import Path

# config.py is a top-level sibling of the audit package (code/config.py),
# never part of it -- every entry point puts code/ on sys.path before
# anything under audit/ is imported, so a plain top-level import always
# resolves, whether this module is run standalone or imported normally.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402


def cache_key(input_bytes: bytes, model: str, prompt_version: str) -> str:
    h = hashlib.sha256()
    h.update(input_bytes)
    h.update(b"\0")
    h.update(model.encode("utf-8"))
    h.update(b"\0")
    h.update(prompt_version.encode("utf-8"))
    return h.hexdigest()


def _path_for(key: str) -> Path:
    return config.CACHE_DIR_LLM / f"{key}.json"


def get(key: str) -> dict | None:
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def put(key: str, value: dict) -> None:
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")
