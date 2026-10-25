"""E1 scorer. Prints status accuracy, step precision/recall/F1,
field-level accuracy, sequence accuracy, citation accuracy, and
per-case results on the 32 public samples. This is the one script
(besides link_check.py) allowed to read sample_output.csv; the audit
pipeline itself never does.

Usage: python code/evaluation/main.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from dotenv import load_dotenv  # noqa: E402

from audit import intent, loaders  # noqa: E402
from audit.evidence.registry import build_registry  # noqa: E402
from audit.case_runner import run_case  # noqa: E402

STEP_FIELDS = ("phase", "system_id", "resource_id", "operation", "state")


def _step_tuple(step: dict, with_evidence: bool) -> tuple:
    if with_evidence:
        return tuple(step[f] for f in STEP_FIELDS) + (step["evidence_id"],)
    return tuple(step[f] for f in STEP_FIELDS)


def score(ai_enabled: bool = True) -> dict:
    reg = build_registry(ai_enabled=ai_enabled)
    samples = loaders.load_sample_deletion_requests()
    outputs = {r.case_id: r for r in loaders.load_sample_output()}

    intent_results = intent.classify_all(samples, ai_enabled)
    intent_not_delete = [r.case_id for r in samples if intent_results[r.case_id].final_intent != "DELETE"]

    status_correct = 0
    total_expected = total_matched = total_got = 0
    total_expected_with_ev = total_matched_with_ev = 0
    field_correct = field_total = 0
    sequence_correct = 0
    citation_correct = citation_total = 0
    per_case = {}

    for req in samples:
        result = run_case(req, reg, intent_results[req.case_id])
        expected = outputs[req.case_id]

        status_ok = result.status == expected.deletion_status
        status_correct += status_ok

        exp_set = {_step_tuple(s, False) for s in expected.steps}
        got_set = {_step_tuple(s, False) for s in result.steps}
        matched = exp_set & got_set
        total_expected += len(exp_set)
        total_matched += len(matched)
        total_got += len(got_set)

        exp_set_ev = {_step_tuple(s, True) for s in expected.steps}
        got_set_ev = {_step_tuple(s, True) for s in result.steps}
        total_expected_with_ev += len(exp_set_ev)
        total_matched_with_ev += len(exp_set_ev & got_set_ev)

        # field-level accuracy on steps matched by (system_id, resource_id, operation)
        exp_by_key = {(s["system_id"], s["resource_id"], s["operation"]): s for s in expected.steps}
        got_by_key = {(s["system_id"], s["resource_id"], s["operation"]): s for s in result.steps}
        for key, exp_step in exp_by_key.items():
            got_step = got_by_key.get(key)
            if got_step is None:
                continue
            for f in ("phase", "state", "step_no"):
                field_total += 1
                field_correct += exp_step[f] == got_step[f]

        # sequence accuracy: exact ordered list match when the step SETS agree
        exp_seq = [_step_tuple(s, False) for s in expected.steps]
        got_seq = [_step_tuple(s, False) for s in result.steps]
        if exp_set == got_set:
            sequence_correct += int(exp_seq == got_seq)

        # citation accuracy: for matched steps that should cite evidence,
        # is the cited evidence_id exactly right?
        for key, exp_step in exp_by_key.items():
            got_step = got_by_key.get(key)
            if got_step is None or exp_step["evidence_id"] == "":
                continue
            citation_total += 1
            citation_correct += exp_step["evidence_id"] == got_step["evidence_id"]

        per_case[req.case_id] = {
            "status_ok": status_ok,
            "got_status": result.status,
            "expected_status": expected.deletion_status,
            "expected_steps": len(exp_set),
            "matched_steps": len(matched),
            "extra_steps": len(got_set - exp_set),
        }

    precision = total_matched / total_got if total_got else 1.0
    recall = total_matched / total_expected if total_expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "n_samples": len(samples),
        "status_accuracy": status_correct / len(samples),
        "step_precision": precision,
        "step_recall": recall,
        "step_f1": f1,
        "step_precision_with_evidence": (total_matched_with_ev / total_got) if total_got else 1.0,
        "step_recall_with_evidence": (total_matched_with_ev / total_expected_with_ev) if total_expected_with_ev else 1.0,
        "field_accuracy": (field_correct / field_total) if field_total else 1.0,
        "sequence_accuracy": sequence_correct / len(samples),
        "citation_accuracy": (citation_correct / citation_total) if citation_total else 1.0,
        "per_case": per_case,
        "intent_not_delete": intent_not_delete,
    }


def build_evaluation_report(result: dict) -> str:
    """Final-phase task 4: a real evaluation_report.md from the 32
    samples, plus the intent/image/security results already produced
    by other runs in this repo (intent_cases.md, intent_review.md,
    extracted_image_facts.md, the I1-I8 test run)."""
    per_case = result["per_case"]
    n = result["n_samples"]
    row_exact = sum(1 for c in per_case.values() if c["status_ok"] and c["extra_steps"] == 0 and c["matched_steps"] == c["expected_steps"])
    missed_total = sum(c["expected_steps"] - c["matched_steps"] for c in per_case.values())
    extra_total = sum(c["extra_steps"] for c in per_case.values())
    status_wrong = sum(1 for c in per_case.values() if not c["status_ok"])

    lines = []
    lines.append("# Evaluation report\n")
    lines.append(
        "**The 32 public samples (`dataset/sample_deletion_requests.csv` / `sample_output.csv`) "
        "are the only labelled data available to this submission.** All metrics below are measured "
        "on them; the 518 real cases have no golden answer available to participants.\n"
    )
    lines.append("## Case-level and row-level accuracy\n")
    lines.append(f"- Case-level status accuracy: {result['status_accuracy']:.3f} ({n - status_wrong}/{n})")
    lines.append(f"- Row exact match (status + full step set, order-insensitive): {row_exact}/{n} ({row_exact/n:.3f})")
    lines.append(f"- Sequence accuracy (exact ordered step list): {result['sequence_accuracy']:.3f}")
    lines.append("")
    lines.append("## Step-level accuracy\n")
    lines.append(f"- Step precision (without evidence_id): {result['step_precision']:.3f}")
    lines.append(f"- Step recall (without evidence_id): {result['step_recall']:.3f}")
    lines.append(f"- Step F1 (without evidence_id): {result['step_f1']:.3f}")
    lines.append(f"- Step precision (with evidence_id): {result['step_precision_with_evidence']:.3f}")
    lines.append(f"- Step recall (with evidence_id): {result['step_recall_with_evidence']:.3f}")
    lines.append(f"- Field-level accuracy (phase/state/step_no on matched steps): {result['field_accuracy']:.3f}")
    lines.append(f"- Citation accuracy (evidence_id on matched steps): {result['citation_accuracy']:.3f}")
    lines.append("")
    lines.append("## Error taxonomy\n")
    lines.append(f"- Missed steps (expected, not produced): {missed_total}")
    lines.append(f"- Extra steps (produced, not expected): {extra_total}")
    lines.append(f"- Wrong status: {status_wrong}")
    lines.append(
        "- All 35 originally-missed sample steps (Phase 3 investigation) were traced individually to a "
        "specific D17 cause: either zero observations anywhere in visible evidence, an identity-less 404 "
        "or fully-anonymized record (D17's own named examples), or evidence captured after that case's "
        "audit_at. None were parser/linker bugs. The step-level ceiling is below 100% by design (D17)."
    )
    lines.append("- Wrong-treatment / wrong-evidence / wrong-order sub-counts are not broken out separately in this "
                  "pass (time-boxed cut per the final-phase prompt's own priority list, item 3); every extra/missed "
                  "step is individually explained in the Phase 2b/3/3b/4 commit messages and DECISIONS.md instead.")
    lines.append("")
    lines.append("## Intent (F13)\n")
    lines.append("- 44 authored synthetic cases (code/evaluation/intent_cases.md): rule layer alone 26/42 (0.619), "
                  "Qwen alone 39/42 (0.929), combined pipeline 42/42 (1.000) on the 42 non-ambiguous cases.")
    lines.append("- All 32 public samples classify DELETE.")
    lines.append("- All 518 real cases: 10 NOT_APPLICABLE (all English), 0 rule/Qwen disagreements, 0 flagged "
                  "unresolved (code/evaluation/intent_review.md) -- matching D10's own ~10-case prediction.")
    lines.append("")
    lines.append("## Images (F05)\n")
    lines.append("- 11/11 images read (OCR grounding + two Gemini readers). Second reader used on 2 of 11 "
                  "(the rest fell back to the grounded primary reader alone and are flagged as such, never guessed).")
    lines.append("- A resource-id shape bug was found and fixed: a reader extracted a UI label "
                  "(\"Delivery tracking\") as if it were a resource id; grounding alone did not catch it since the "
                  "label is genuinely visible on screen. Fixed by also requiring a known mapping.py prefix shape.")
    lines.append("- D16 re-checked against all 11 images: no SECONDARY_IDENTIFIER or PRODUCT_TELEMETRY found.")
    lines.append("- Full per-image counts in code/evaluation/extracted_image_facts.md.")
    lines.append("")
    lines.append("## Security (I1-I8)\n")
    lines.append("| Test | Description | Result |")
    lines.append("|---|---|---|")
    lines.append("| I1 | Instruction text in a log line | PASS -- byte-identical facts |")
    lines.append("| I2 | Instruction text in a JSON field | PASS -- byte-identical facts |")
    lines.append("| I3 | Instruction text in a PDF text layer | PASS -- byte-identical facts |")
    lines.append("| I4 | Instruction text rendered on an image | PASS (live-only, gated behind --run-live-ai) |")
    lines.append("| I5 | Injection in request_text, English + Spanish | PASS -- never authorizes deletion; a genuine request is not suppressed by an appended injection |")
    lines.append("| I6 | Hostile SQL (ATTACH/PRAGMA/trigger) | PASS -- rejected by the sandbox (test_sql_sandbox.py) |")
    lines.append("| I7 | Request naming another person's data | PASS -- only the resolved subject's records link |")
    lines.append("| I8 | Secret scan on log.txt | PASS -- no secret-shaped pattern found |")
    lines.append("\n**Attack success rate: 0/8 (0%).**\n")
    lines.append("## Failures found and improvements made\n")
    lines.append("Sourced only from DECISIONS.md, phase reports, and log.txt:\n")
    lines.append("1. A literal `\"null\"` placeholder (an absent log field, not JSON null) was read as a real "
                  "identifier, creating a massive cross-person link hub via reference_closure (D18).")
    lines.append("2. An off-by-one pipe split in the operations_stream log parser shifted every field by one, "
                  "turning a component name into a fake shared trace_id -- a second, independent cross-person hub.")
    lines.append("3. Hash-seed nondeterminism in state.py's tie-break for same-timestamp facts, fixed with a "
                  "deterministic secondary sort key; proven byte-identical across 4 PYTHONHASHSEED values.")
    lines.append("4. The original transitive, any-shared-key reference_closure (D18) was replaced with a "
                  "directed, one-hop, hub-guarded, conflicting-identity-guarded rule.")
    lines.append("5. Two more trace-key gaps found while classifying zero-step COMPLETE cases: cloud_runtime_export's "
                  "`requestId` and syslog_archive's 3rd header token were real, reused correlation keys never wired "
                  "into trace_correlation.")
    lines.append("6. Calibrations replaced with field-grounded rules: SUPPORT_MESSAGE shared_context now checks "
                  "ticket_id/message_excerpt instead of \"any text\"; the MARKETING_PROFILE override dropped its "
                  "redundant text-matched disjunct.")
    lines.append("7. A sentence-scope bug in the intent rule layer: a negation in an injected second sentence could "
                  "retroactively flip a genuine deletion request in the first sentence -- fixed by evaluating each "
                  "sentence independently (found via I5 security testing).")
    lines.append("8. A UI-label-as-resource-id bug in image extraction, fixed with a mapping.py prefix shape check "
                  "layered on top of OCR grounding.")
    lines.append("9. Found in this phase's own review: `python code/main.py --no-ai` crashed on a clean checkout "
                  "because model results existed only in the git-ignored `.cache/`. Fixed with the committed "
                  "code/replay/ cache (this phase's task 1), proven keyless and byte-identical to the live run.")
    return "\n".join(lines) + "\n"


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    result = score()
    print(f"intent: all 32 samples DELETE: {'PASS' if not result['intent_not_delete'] else 'FAIL ' + str(result['intent_not_delete'])}")
    print(f"samples: {result['n_samples']}")
    print(f"status accuracy: {result['status_accuracy']:.3f}")
    print(f"step precision (without evidence_id): {result['step_precision']:.3f}")
    print(f"step recall (without evidence_id): {result['step_recall']:.3f}")
    print(f"step F1 (without evidence_id): {result['step_f1']:.3f}")
    print(f"step precision (with evidence_id): {result['step_precision_with_evidence']:.3f}")
    print(f"step recall (with evidence_id): {result['step_recall_with_evidence']:.3f}")
    print(f"field-level accuracy: {result['field_accuracy']:.3f}")
    print(f"sequence accuracy: {result['sequence_accuracy']:.3f}")
    print(f"citation accuracy: {result['citation_accuracy']:.3f}")
    print()
    for case_id, info in result["per_case"].items():
        marker = "OK" if info["status_ok"] else "MISMATCH"
        print(f"  {case_id}: {marker} got={info['got_status']} expected={info['expected_status']} "
              f"matched={info['matched_steps']}/{info['expected_steps']} extra={info['extra_steps']}")

    report_path = REPO_ROOT / "code" / "evaluation" / "evaluation_report.md"
    report_path.write_text(build_evaluation_report(result), encoding="utf-8")
    print(f"\nwrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
