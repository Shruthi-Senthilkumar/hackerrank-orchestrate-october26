"""Ghost Data Still Exists - deletion audit pipeline entry point.

Runs the full pipeline (intent -> identity -> linking -> state ->
policy -> detectors -> decision -> planner -> validator -> writer) over
every case in dataset/deletion_requests.csv and writes output.csv at
the repository root.

`--no-ai` runs rules/cache only: code/audit/llm/client.py refuses any
live model call in that mode (AIDisabledError), so a cache miss is a
hard failure, never a silent fallback to a guess. Without `--no-ai`,
real Groq/Gemini calls are made for anything not already cached (F13
intent; F05 images are wired in as they land).
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

from audit import intent, loaders  # noqa: E402
from audit.case_runner import run_case  # noqa: E402
from audit.evidence.registry import build_registry  # noqa: E402
from audit.llm import usage  # noqa: E402
from audit.output import serialize_steps, validate_row, write_output_csv  # noqa: E402
from audit.trace_writer import write_case_trace  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "output.csv"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists - deletion audit pipeline",
    )
    parser.add_argument(
        "--cases",
        default=None,
        help="Comma-separated case_id list to run instead of the full dataset "
        "(debug only; never used to change logic by ID).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Never make a live model call: intent/vision must come from cache "
        "or deterministic rules only. A cache miss raises AIDisabledError.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Also write a per-case E5 trace JSON file under agent-trace/ "
        "(git-ignored; never part of the submission).",
    )
    return parser


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = build_arg_parser()
    args = parser.parse_args()
    ai_enabled = not args.no_ai

    requests = loaders.load_deletion_requests()
    if args.cases:
        wanted = set(args.cases.split(","))
        requests = [r for r in requests if r.case_id in wanted]

    requests = sorted(requests, key=lambda r: r.case_id)

    ledger_before = len(usage.read_all())

    print(f"Classifying intent for {len(requests)} case(s) (ai_enabled={ai_enabled})...")
    intent_results = intent.classify_all(requests, ai_enabled)

    print(f"Loading evidence registry for {len(requests)} case(s)...")
    registry = build_registry(ai_enabled=ai_enabled)

    rows = []
    status_counts = Counter()
    reported_status_counts = Counter()
    fallback_count = 0
    bad_count = 0
    intent_not_applicable = 0
    intent_flagged = 0
    start = time.monotonic()

    for req in requests:
        result = run_case(req, registry, intent_results[req.case_id])
        validation = validate_row(req.case_id, result.status, result.steps, req.audit_at)
        if not validation.ok:
            bad_count += 1
            print(f"  WARNING: {req.case_id} failed validation: {validation.errors}")

        if result.trace.policy_fallbacks or result.trace.fallback_reason:
            fallback_count += 1
        if intent_results[req.case_id].final_intent == "NOT_APPLICABLE":
            intent_not_applicable += 1
        if intent_results[req.case_id].flagged:
            intent_flagged += 1

        status_counts[result.status] += 1
        reported_status_counts[req.reported_status] += 1

        rows.append((req.case_id, result.status, serialize_steps(result.steps)))

        if args.trace:
            write_case_trace(result)

    elapsed = time.monotonic() - start

    rows.sort(key=lambda r: r[0])
    write_output_csv(rows, OUTPUT_PATH)

    ledger_after = usage.read_all()
    new_entries = ledger_after[ledger_before:]
    real_calls = [e for e in new_entries if not e["cache_hit"]]
    total_input_tokens = sum(e["input_tokens"] for e in new_entries)
    total_output_tokens = sum(e["output_tokens"] for e in new_entries)

    print(f"Wrote {len(rows)} row(s) to {OUTPUT_PATH}")
    print(f"Runtime: {elapsed:.1f}s")
    print(f"Rows that failed validation (should be 0): {bad_count}")
    print(f"Cases with at least one policy fallback: {fallback_count}")
    print(f"Intent NOT_APPLICABLE: {intent_not_applicable}  (flagged unresolved: {intent_flagged})")
    print(
        f"Model calls this run: {len(real_calls)} live / {len(new_entries)} total logical requests "
        f"(input_tokens={total_input_tokens}, output_tokens={total_output_tokens})"
    )
    print("Decided status distribution:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print("reported_status distribution (a claim, informational only, never used to decide):")
    for status, count in sorted(reported_status_counts.items()):
        print(f"  {status}: {count}")

    return 1 if bad_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
