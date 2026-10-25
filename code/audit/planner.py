"""F11 planner (PRD 7.8, 4.4, 4.5).

Builds the ordered step list for one case from its resource decisions
and detector findings. For COMPLETE, only verification steps, each
citing the evidence that proves the current state. For INCOMPLETE,
findings (with evidence) + remediation (empty evidence) + verification
of the post-remediation state for every evaluated resource, including
ones that were already compliant (PRD text: "VERIFICATION for retained
records that must remain... and for compliant tombstones, per the
sample pattern" -- measured on the 32 samples: every linked, decided
resource gets a verification entry even in an INCOMPLETE case, and
EVERY verification step in an INCOMPLETE case uses an empty evidence_id,
even for an already-compliant resource, because the whole verification
list describes the state that must hold after remediation, not the
current state).

No dependency sorter beyond the deterministic (phase, operation order,
system_id, resource_id) sort is used -- PRD 3.2 fact 3 confirms this
single sort reproduces all 32 sample orderings, and the operation-order
table itself already places DISABLE_DATA_FLOW/BLOCK_RESTORE before
DELETE_RECORD/REDACT_RECORD/ANONYMIZE_RECORD, which is what AGENTS.md
6.5 means by "disable flows and block unsafe restores before changing
dependent records."
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.decision import ResourceDecision
    from audit.detectors import Finding
    from audit.state import ResourceState
else:
    from .decision import ResourceDecision
    from .detectors import Finding
    from .state import ResourceState

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}

OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 4,
    "BLOCK_RESTORE": 5,
    "DELETE_RECORD": 6,
    "REDACT_RECORD": 7,
    "ANONYMIZE_RECORD": 8,
    "VERIFY_RECORD_ABSENT": 9,
    "VERIFY_RECORD_PRESENT": 10,
    "VERIFY_RECORD_REDACTED": 11,
    "VERIFY_RECORD_ANONYMIZED": 12,
    "VERIFY_DATA_FLOW_DISABLED": 13,
    "VERIFY_RESTORE_BLOCKED": 14,
}

_VERIFY_OP_AND_STATE_BY_FINAL_STATE = {
    "ABSENT": ("VERIFY_RECORD_ABSENT", "ABSENT"),
    "PRESENT": ("VERIFY_RECORD_PRESENT", "PRESENT"),
    "REDACTED": ("VERIFY_RECORD_REDACTED", "REDACTED"),
    "ANONYMIZED": ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
}


def _step(phase, system_id, resource_id, operation, state, evidence_id) -> dict:
    return {
        "phase": phase,
        "system_id": system_id,
        "resource_id": resource_id,
        "operation": operation,
        "state": state,
        "evidence_id": evidence_id,
    }


def _sort_key(step: dict) -> tuple:
    return (PHASE_ORDER[step["phase"]], OPERATION_ORDER[step["operation"]], step["system_id"], step["resource_id"])


def _number(steps: list[dict]) -> list[dict]:
    steps = sorted(steps, key=_sort_key)
    for i, s in enumerate(steps, start=1):
        s["step_no"] = i
    return steps


def plan_steps(
    status: str,
    resource_decisions: list[ResourceDecision],
    active_flow_findings: list[Finding],
    restore_findings: list[Finding],
    compliant_flow_states: list[ResourceState] = (),
    compliant_backup_states: list[ResourceState] = (),
) -> list[dict]:
    """compliant_flow_states/compliant_backup_states: linked
    ACTIVE_DATA_FLOW/BACKUP_ARCHIVE resources that are NOT a finding
    (already disabled/restore-blocked). These are detector-only
    categories (decision.py's _DETECTOR_ONLY_CATEGORIES) with no
    deletion_rules.csv row, so they never reach resource_decisions;
    without this they would be silently dropped from the output even
    though the samples verify them (e.g. case_27's backup_5970 gets
    exactly one step, VERIFY_RESTORE_BLOCKED, with no separate
    VERIFY_RECORD_PRESENT for the archive itself)."""
    if status == "NOT_APPLICABLE":
        return []

    steps: list[dict] = []

    if status == "INCOMPLETE":
        for d in resource_decisions:
            if not d.is_violation:
                continue
            if d.violation_kind == "remaining_record":
                steps.append(_step("FINDING", d.system_id, d.resource_id, "REPORT_REMAINING_RECORD", "PRESENT", d.evidence_id))
            elif d.violation_kind == "exposed_pii":
                steps.append(_step("FINDING", d.system_id, d.resource_id, "REPORT_EXPOSED_PII", "PRESENT", d.evidence_id))
            # "retained_missing" has no matching FINDING operation in the
            # allowed list (nothing fits "something required is gone");
            # it still makes the case INCOMPLETE via decide_status, but
            # is reported only in the trace (E5), never as an invalid step.
        for f in active_flow_findings:
            steps.append(_step("FINDING", f.system_id, f.resource_id, "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", f.evidence_id))
        for f in restore_findings:
            steps.append(_step("FINDING", f.system_id, f.resource_id, "REPORT_RESTORE_RISK", "ACTIVE", f.evidence_id))

        for f in active_flow_findings:
            steps.append(_step("REMEDIATION", f.system_id, f.resource_id, "DISABLE_DATA_FLOW", "DISABLED", ""))
        for f in restore_findings:
            steps.append(_step("REMEDIATION", f.system_id, f.resource_id, "BLOCK_RESTORE", "BLOCKED", ""))
        for d in resource_decisions:
            if d.is_violation and d.remediation_op:
                steps.append(_step("REMEDIATION", d.system_id, d.resource_id, d.remediation_op, d.final_state, ""))

        for d in resource_decisions:
            verify = _VERIFY_OP_AND_STATE_BY_FINAL_STATE.get(d.final_state)
            if verify:
                op, st = verify
                steps.append(_step("VERIFICATION", d.system_id, d.resource_id, op, st, ""))
        for f in active_flow_findings:
            steps.append(_step("VERIFICATION", f.system_id, f.resource_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""))
        for f in restore_findings:
            steps.append(_step("VERIFICATION", f.system_id, f.resource_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ""))
        for s in compliant_flow_states:
            steps.append(_step("VERIFICATION", s.system_id, s.resource_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""))
        for s in compliant_backup_states:
            steps.append(_step("VERIFICATION", s.system_id, s.resource_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ""))

    elif status == "COMPLETE":
        for d in resource_decisions:
            verify = _VERIFY_OP_AND_STATE_BY_FINAL_STATE.get(d.final_state)
            if verify:
                op, st = verify
                steps.append(_step("VERIFICATION", d.system_id, d.resource_id, op, st, d.evidence_id))
        # active_flow_findings/restore_findings can never be non-empty for
        # a COMPLETE case by construction (decide_status would have made
        # it INCOMPLETE); only the compliant flow/backup states apply.
        for s in compliant_flow_states:
            steps.append(_step("VERIFICATION", s.system_id, s.resource_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", s.evidence_id))
        for s in compliant_backup_states:
            steps.append(_step("VERIFICATION", s.system_id, s.resource_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", s.evidence_id))

    return _number(steps)
