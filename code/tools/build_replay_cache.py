"""Final phase task 1: populates code/replay/ from the current,
already-live-tested .cache/ state -- the final intent decision per
request (keyed by sha256 of the request text) and the agreed image
facts per image (keyed by sha256 of the file bytes), each with their
ORIGINAL usage. Run once; the result is committed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from dotenv import load_dotenv  # noqa: E402

from audit import intent, loaders  # noqa: E402
from audit.evidence.registry import build_registry  # noqa: E402
from audit.llm import replay  # noqa: E402
from audit.llm.usage import read_all  # noqa: E402


def _usage_for(entries: list[dict], model: str) -> dict:
    for e in reversed(entries):  # latest non-cache-hit entry for this model
        if e["model"] == model and not e["cache_hit"]:
            return {
                "provider": e["provider"], "model": e["model"], "prompt_version": e["prompt_version"],
                "input_tokens": e["input_tokens"], "output_tokens": e["output_tokens"],
                "thinking_tokens": e["thinking_tokens"], "latency_s": e["latency_s"],
            }
    for e in reversed(entries):
        if e["model"] == model:
            u = e.get("original_usage") or e
            return {
                "provider": e["provider"], "model": e["model"], "prompt_version": e["prompt_version"],
                "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                "thinking_tokens": u.get("thinking_tokens", 0), "latency_s": e["latency_s"],
            }
    return {"provider": "", "model": model, "prompt_version": "", "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "latency_s": 0.0}


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    ledger = read_all()

    # Two SEPARATE calls, matching the exact batch groupings already
    # cached by earlier runs (code/evaluation/main.py ran samples
    # alone; code/main.py ran the 518 real cases alone) -- combining
    # them into one 550-item call would re-batch differently and miss
    # the cache, forcing new live calls against an exhausted daily
    # token budget.
    samples = loaders.load_sample_deletion_requests()
    real = sorted(loaders.load_deletion_requests(), key=lambda r: r.case_id)
    results = {}
    results.update(intent.classify_all(samples, ai_enabled=True))
    results.update(intent.classify_all(real, ai_enabled=True))
    all_requests = samples + real

    n_intent = 0
    for req in all_requests:
        r = results[req.case_id]
        replay.put_intent(req.request_text, {
            "final_intent": r.final_intent, "rule_verdict": r.rule_verdict, "qwen_intent": r.qwen_intent,
            "qwen_language": r.qwen_language, "qwen_evidence_phrase": r.qwen_evidence_phrase,
            "escalated": r.escalated, "resolution": r.resolution, "flagged": r.flagged,
            "usage": _usage_for(ledger, "qwen/qwen3.8-27b"),
        })
        n_intent += 1

    image_reports = []
    build_registry(use_cache=False, ai_enabled=True, image_reports=image_reports)

    import config as _cfg

    n_images = 0
    for fid in loaders.load_evidence_files():
        pass
    from audit import paths

    for ev in loaders.load_evidence_files():
        if not ev.file_path.endswith(".png"):
            continue
        report = next((r for r in image_reports if r.file_id == ev.file_id), None)
        if report is None:
            continue
        image_bytes = paths.resolve_evidence(ev.file_path).read_bytes()
        replay.put_image(image_bytes, {
            "agreed": report.agreed,
            "report": {
                "document_type": report.document_type, "system_id": report.system_id,
                "facts_extracted": report.facts_extracted, "facts_grounded": report.facts_grounded,
                "facts_dropped": report.facts_dropped, "disagreements": report.disagreements,
                "second_reader_used": report.second_reader_used,
                "second_reader_available": report.second_reader_available, "flagged": report.flagged,
            },
            "primary_usage": _usage_for(ledger, _cfg.EXTRACT_MODEL),
            "second_usage": _usage_for(ledger, _cfg.EXTRACT_MODEL_RARE) if report.second_reader_used else None,
        })
        n_images += 1

    print(f"wrote {n_intent} intent replay entries, {n_images} image replay entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
