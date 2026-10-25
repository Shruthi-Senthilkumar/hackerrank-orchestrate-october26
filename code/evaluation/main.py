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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
