"""Phase 4 task 4(c): run intent classification on all 518 real
requests and write code/evaluation/intent_review.md listing EVERY
request not decided DELETE and every rule/Qwen disagreement, with
language, the evidence phrase, and the final decision, for hand
review. Never used to tune the rule layer or prompt beyond fixing a
clear rule bug (reported separately, not here).

Run: python code/evaluation/intent_review.py
"""

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from dotenv import load_dotenv  # noqa: E402

from audit import intent, loaders  # noqa: E402


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    requests = sorted(loaders.load_deletion_requests(), key=lambda r: r.case_id)
    results = intent.classify_all(requests, ai_enabled=True)

    not_delete = [r for r in requests if results[r.case_id].final_intent != "DELETE"]
    disagreements = [
        r for r in requests
        if results[r.case_id].rule_verdict != "UNSURE"
        and results[r.case_id].qwen_intent is not None
        and (
            (results[r.case_id].qwen_intent == "UNCLEAR")
            or (results[r.case_id].rule_verdict != results[r.case_id].qwen_intent)
        )
    ]
    by_language = Counter(results[r.case_id].qwen_language for r in not_delete)

    lines = []
    lines.append("# Intent review: all 518 real requests (Phase 4 task 4c)\n")
    lines.append(f"Total requests: {len(requests)}")
    lines.append(f"Not decided DELETE (NOT_APPLICABLE): {len(not_delete)}")
    lines.append(f"Rule/Qwen disagreements (including any Qwen UNCLEAR): {len(disagreements)}\n")
    lines.append("## Not-DELETE requests, by language\n")
    lines.append("| language | count |")
    lines.append("|---|---|")
    for lang, count in sorted(by_language.items(), key=lambda x: -x[1]):
        lines.append(f"| {lang} | {count} |")

    lines.append("\n## Every request not decided DELETE\n")
    lines.append("| case_id | language | rule | qwen | resolution | escalated | flagged | evidence_phrase |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in not_delete:
        ir = results[r.case_id]
        lines.append(
            f"| {r.case_id} | {ir.qwen_language} | {ir.rule_verdict} | {ir.qwen_intent} | "
            f"{ir.resolution} | {ir.escalated} | {ir.flagged} | {ir.qwen_evidence_phrase!r} |"
        )

    lines.append("\n## Every rule/Qwen disagreement (whether or not it changed the final answer)\n")
    lines.append("| case_id | language | rule | qwen | final_intent | resolution | evidence_phrase |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in disagreements:
        ir = results[r.case_id]
        lines.append(
            f"| {r.case_id} | {ir.qwen_language} | {ir.rule_verdict} | {ir.qwen_intent} | "
            f"{ir.final_intent} | {ir.resolution} | {ir.qwen_evidence_phrase!r} |"
        )

    lines.append("\n## Flagged unresolved (rule/Qwen disagreement never resolved; defaulted to NOT_APPLICABLE per D10)\n")
    flagged = [r for r in requests if results[r.case_id].flagged]
    if flagged:
        lines.append("| case_id | language | rule | qwen (escalated pass) | evidence_phrase |")
        lines.append("|---|---|---|---|---|")
        for r in flagged:
            ir = results[r.case_id]
            lines.append(f"| {r.case_id} | {ir.qwen_language} | {ir.rule_verdict} | {ir.qwen_intent} | {ir.qwen_evidence_phrase!r} |")
    else:
        lines.append("None -- every disagreement resolved on the single-text escalation pass.")

    out_path = REPO_ROOT / "code" / "evaluation" / "intent_review.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"total={len(requests)} not_delete={len(not_delete)} disagreements={len(disagreements)} flagged={len(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
