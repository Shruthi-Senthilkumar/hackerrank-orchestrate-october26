"""Local OCR adapter (Phase 4 F05, PRD 8.3): a confirmation/grounding
source only, never a decision-maker. `extract_text()` is the whole
interface so the OCR engine can be swapped (PaddleOCR, RapidOCR, or
anything else) without touching any caller.

RapidOCR (via onnxruntime) is used here directly, per the Phase 4
task's own explicit instruction (PRD 8.3 names PaddleOCR primary with
RapidOCR as a fallback; the Phase 4 kickoff prompt instead says to use
RapidOCR via onnxruntime, so that supersedes the PRD here).

OCR output is cached by SHA-256 of the image's own bytes (never the
model-extraction prompt version -- OCR has no prompt and never
changes unless the image itself does) under `.cache/ocr_cache/`
(git-ignored).
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402

OCR_CACHE_DIR = config.CACHE_DIR / "ocr_cache"


class OCRAdapter(Protocol):
    def extract_text(self, image_bytes: bytes) -> str: ...


class RapidOCRAdapter:
    """Thin wrapper around rapidocr_onnxruntime.RapidOCR. Loads the
    model lazily (first call only) since constructing it loads ONNX
    model weights from disk."""

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def extract_text(self, image_bytes: bytes) -> str:
        import numpy as np
        from PIL import Image
        import io

        engine = self._get_engine()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        result, _elapse = engine(arr)
        if not result:
            return ""
        return "\n".join(line[1] for line in result)


_DEFAULT_ADAPTER: OCRAdapter = RapidOCRAdapter()


def _cache_path(key: str) -> Path:
    return OCR_CACHE_DIR / f"{key}.json"


def ocr_text(image_bytes: bytes, adapter: OCRAdapter = None) -> str:
    """Cached OCR extraction. Returns the plain text RapidOCR (or
    whatever adapter is given) read off the image."""
    key = hashlib.sha256(image_bytes).hexdigest()
    cache_path = _cache_path(key)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))["text"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    engine = adapter or _DEFAULT_ADAPTER
    text = engine.extract_text(image_bytes)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    return text
