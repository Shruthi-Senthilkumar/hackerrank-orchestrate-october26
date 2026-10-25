"""Phase 4 task 7: reads the usage ledger (.cache/usage_ledger.jsonl)
and writes code/evaluation/usage_report.md in the required shape:
providers and models, call counts, input/output/thinking tokens,
total and per-request average, estimated cost at list prices, cache
hits.

This is proven against the CURRENT ledger here; it is not run for the
final report until the full-dataset run that produces output.csv
(Phase 6), per the Phase 4 task's own instruction.

Usage: python code/tools/make_usage_report.py [--out PATH]
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

import config  # noqa: E402
from audit.llm import usage  # noqa: E402


def build_report(entries: list[dict]) -> str:
    by_model = defaultdict(lambda: {
        "provider": "", "calls": 0, "cache_hits": 0, "input_tokens": 0,
        "output_tokens": 0, "thinking_tokens": 0, "errors": 0,
    })
    for e in entries:
        m = by_model[e["model"]]
        m["provider"] = e["provider"]
        m["calls"] += 1
        m["cache_hits"] += int(e["cache_hit"])
        m["input_tokens"] += e["input_tokens"]
        m["output_tokens"] += e["output_tokens"]
        m["thinking_tokens"] += e.get("thinking_tokens", 0)
        m["errors"] += int(bool(e.get("error")))

    total_calls = len(entries)
    total_cache_hits = sum(m["cache_hits"] for m in by_model.values())
    total_live_calls = total_calls - total_cache_hits
    total_input = sum(m["input_tokens"] for m in by_model.values())
    total_output = sum(m["output_tokens"] for m in by_model.values())
    total_thinking = sum(m["thinking_tokens"] for m in by_model.values())
    total_tokens = total_input + total_output + total_thinking

    def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
        price = config.PRICING_PER_MILLION_TOKENS.get(model)
        if not price:
            return 0.0
        return (input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"]

    total_cost = sum(cost_for(model, m["input_tokens"], m["output_tokens"]) for model, m in by_model.items())

    lines = []
    lines.append("# Usage report\n")
    lines.append(
        "Both providers are used on their free tiers in this project; the `estimated cost` "
        "columns are list-price estimates (see code/config.py's PRICING_PER_MILLION_TOKENS), "
        "not actual billed amounts. `cache hits` are logical requests served from "
        "code/audit/llm/cache.py with zero network calls.\n"
    )
    lines.append("## Per-model totals\n")
    lines.append("| provider | model | calls (logical) | live calls | cache hits | input tokens | output tokens | thinking tokens | errors | est. cost (USD) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for model, m in sorted(by_model.items()):
        cost = cost_for(model, m["input_tokens"], m["output_tokens"])
        lines.append(
            f"| {m['provider']} | {model} | {m['calls']} | {m['calls'] - m['cache_hits']} | {m['cache_hits']} | "
            f"{m['input_tokens']} | {m['output_tokens']} | {m['thinking_tokens']} | {m['errors']} | ${cost:.4f} |"
        )

    lines.append("\n## Overall totals\n")
    lines.append(f"- Total logical requests: {total_calls}")
    lines.append(f"- Live calls: {total_live_calls}")
    lines.append(f"- Cache hits: {total_cache_hits}")
    lines.append(f"- Total input tokens: {total_input}")
    lines.append(f"- Total output tokens: {total_output}")
    lines.append(f"- Total thinking tokens: {total_thinking}")
    lines.append(f"- Total tokens: {total_tokens}")
    lines.append(f"- Average tokens per logical request: {total_tokens / total_calls:.1f}" if total_calls else "- Average tokens per logical request: n/a")
    lines.append(f"- Estimated total cost (list price): ${total_cost:.4f}")
    lines.append(f"- Estimated average cost per request (list price): ${(total_cost / total_calls):.6f}" if total_calls else "- Estimated average cost per request: n/a")
    lines.append(f"- Actual incurred cost (both providers on free tier for this run): $0.00")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO_ROOT / "code" / "evaluation" / "usage_report.md"))
    args = parser.parse_args()

    entries = usage.read_all()
    report = build_report(entries)
    out_path = Path(args.out)
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path} from {len(entries)} ledger entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
