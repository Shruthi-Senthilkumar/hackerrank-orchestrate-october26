"""E5 per-case trace writer. Writes one JSON file per case under
agent-trace/ (git-ignored; never part of the submission's code.zip,
never read back by audit logic) recording identity resolution, every
linked resource and the rule that linked it, computed resource states
with their citing evidence, policy decisions and any fallback used,
detector findings, the final status, and the reported_status/reported_at
fields explicitly labeled as claims -- never used to decide anything,
kept only so a reviewer can see what the workflow claimed versus what
the audit actually found.
"""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.case_runner import CaseResult
else:
    from .case_runner import CaseResult

DEFAULT_TRACE_DIR = Path(__file__).resolve().parent.parent.parent / "agent-trace"


def trace_to_dict(result: CaseResult) -> dict:
    t = result.trace
    return {
        "case_id": t.case_id,
        "status": t.status,
        "intent_result": t.intent_result,
        "classify_request_corroboration": t.classify_request_corroboration,
        "reported_status_claim": t.reported_status_claim,
        "reported_at_claim": t.reported_at_claim,
        "identity_resolution": t.identity_resolution,
        "linked_resources": t.linked_resources,
        "resource_states": t.resource_states,
        "resource_decisions": t.resource_decisions,
        "policy_fallbacks": t.policy_fallbacks,
        "active_flow_findings": t.active_flow_findings,
        "restore_findings": t.restore_findings,
        "fallback_reason": t.fallback_reason,
        "steps": result.steps,
    }


def write_case_trace(result: CaseResult, trace_dir: Path = DEFAULT_TRACE_DIR) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{result.case_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace_to_dict(result), f, sort_keys=True, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    return path
