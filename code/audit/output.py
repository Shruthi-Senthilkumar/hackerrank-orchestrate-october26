"""F12 output validator and writer.

Validates every row against the full output contract (PRD section 6.3,
problem_statement.md) before writing output.csv. A failing row is
replaced by a safe fallback row and counted, never silently dropped.
"""

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.planner import OPERATION_ORDER, PHASE_ORDER
    from audit.timeview import build_time_view
else:
    from .planner import OPERATION_ORDER, PHASE_ORDER
    from .timeview import build_time_view

VALID_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
VALID_PHASES = set(PHASE_ORDER)
VALID_OPERATIONS = set(OPERATION_ORDER)

# Phase/operation combinations the problem statement actually allows.
_FINDING_OPS = {"REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"}
_REMEDIATION_OPS = {"DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"}
_VERIFICATION_OPS = {
    "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED",
}
_OPS_BY_PHASE = {"FINDING": _FINDING_OPS, "REMEDIATION": _REMEDIATION_OPS, "VERIFICATION": _VERIFICATION_OPS}

_VALID_STATE_BY_OP = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

_REQUIRED_FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}


@dataclass
class ValidationResult:
    ok: bool
    errors: list


def _visible_evidence_ids(audit_at) -> set:
    """Every file_id, activity_id, and audit_id visible at audit_at,
    via TimeView -- the single gateway -- never a hand-filtered copy
    of the raw tables."""
    time_view = build_time_view(audit_at)
    ids = {e.file_id for e in time_view.visible_evidence_files()}
    ids |= {a.activity_id for a in time_view.visible_activity()}
    ids |= {a.audit_id for a in time_view.visible_audit_log()}
    return ids


def validate_row(case_id: str, status: str, steps: list[dict], audit_at) -> ValidationResult:
    errors = []

    if status not in VALID_STATUSES:
        errors.append(f"invalid status {status!r}")
        return ValidationResult(False, errors)

    if status == "NOT_APPLICABLE":
        if steps != []:
            errors.append("NOT_APPLICABLE must have steps=[]")
        return ValidationResult(len(errors) == 0, errors)

    if not isinstance(steps, list):
        errors.append("steps is not a list")
        return ValidationResult(False, errors)

    valid_evidence_ids = _visible_evidence_ids(audit_at)
    phase_seen_max = -1
    for i, step in enumerate(steps, start=1):
        if set(step.keys()) != _REQUIRED_FIELDS:
            errors.append(f"step {i}: field set mismatch: {sorted(step.keys())}")
            continue
        if step["step_no"] != i:
            errors.append(f"step {i}: step_no {step['step_no']} is not consecutive from 1")
        phase = step["phase"]
        if phase not in VALID_PHASES:
            errors.append(f"step {i}: invalid phase {phase!r}")
            continue
        if PHASE_ORDER[phase] < phase_seen_max:
            errors.append(f"step {i}: phase order violated ({phase} after a later phase)")
        phase_seen_max = max(phase_seen_max, PHASE_ORDER[phase])

        op = step["operation"]
        if op not in VALID_OPERATIONS:
            errors.append(f"step {i}: invalid operation {op!r}")
            continue
        if op not in _OPS_BY_PHASE[phase]:
            errors.append(f"step {i}: operation {op} not allowed in phase {phase}")
        expected_state = _VALID_STATE_BY_OP.get(op)
        if expected_state and step["state"] != expected_state:
            errors.append(f"step {i}: state {step['state']!r} does not match operation {op}")

        evidence_id = step["evidence_id"]
        is_remediation_or_future = phase in ("REMEDIATION",) or (
            phase == "VERIFICATION" and status == "INCOMPLETE"
        )
        if is_remediation_or_future:
            if evidence_id != "":
                errors.append(f"step {i}: {phase} step must have empty evidence_id, got {evidence_id!r}")
        else:
            if evidence_id == "":
                errors.append(f"step {i}: {phase} step (status {status}) must cite evidence")
            elif evidence_id not in valid_evidence_ids:
                errors.append(f"step {i}: evidence_id {evidence_id!r} not visible or unknown")

    return ValidationResult(len(errors) == 0, errors)


def serialize_steps(steps: list[dict]) -> str:
    clean = [
        {k: step[k] for k in ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")}
        for step in steps
    ]
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_output_csv(rows: list[tuple], output_path: Path) -> None:
    """rows: list of (case_id, deletion_status, steps_json_string),
    already sorted by case_id."""
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for case_id, status, steps_json in rows:
            writer.writerow([case_id, status, steps_json])
