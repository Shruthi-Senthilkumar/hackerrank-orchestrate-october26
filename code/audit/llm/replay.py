"""Committed replay cache (final phase, task 1): code/replay/ holds the
model results actually used, so a keyless clean checkout can reproduce
output.csv with zero live calls. Lookup order everywhere: replay ->
.cache/ -> a live call only if keys exist and ai_enabled. Deterministic
JSON (sorted keys, LF).
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402

REPLAY_DIR = config.REPO_ROOT / "code" / "replay"
INTENT_DIR = REPLAY_DIR / "intent"
IMAGE_DIR = REPLAY_DIR / "images"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2))
        f.write("\n")


def get_intent(text: str) -> dict | None:
    return _read(INTENT_DIR / f"{text_hash(text)}.json")


def put_intent(text: str, value: dict) -> None:
    _write(INTENT_DIR / f"{text_hash(text)}.json", value)


def get_image(image_bytes: bytes) -> dict | None:
    return _read(IMAGE_DIR / f"{image_hash(image_bytes)}.json")


def put_image(image_bytes: bytes, value: dict) -> None:
    _write(IMAGE_DIR / f"{image_hash(image_bytes)}.json", value)
