"""F10 status decision (PRD 7.7).

Combines policy outcomes (per-resource compliance) and detector
findings (active flows, restore risks) into one COMPLETE/INCOMPLETE/
NOT_APPLICABLE status. reported_status never enters this decision; it
is a claim, logged in the trace only (E5), never read here.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit import policy
    from audit.detectors import Finding
    from audit.state import ResourceState
else:
    from . import policy
    from .detectors import Finding
    from .state import ResourceState

# Categories whose tombstone/RETAIN-style record must itself remain
# present; its absence is a violation (unlike SUPPORT_MESSAGE/
# EMAIL_DELIVERY_LOG/ANALYTICS_PROFILE/PRODUCT_TELEMETRY, where a fully
# absent record is acceptable over-compliance, not a violation). Per
# PRD 7.5's table: "Tombstone absent: retained record unavailable."
_ABSENCE_IS_VIOLATION_FOR_REDACT = {"ACCOUNT_TOMBSTONE"}

_REMEDIATION_OP_BY_ACTION = {
    "DELETE": "DELETE_RECORD",
    "REDACT": "REDACT_RECORD",
    "ANONYMIZE": "ANONYMIZE_RECORD",
}
_FINAL_STATE_BY_ACTION = {
    "DELETE": "ABSENT",
    "REDACT": "REDACTED",
    "ANONYMIZE": "ANONYMIZED",
}


@dataclass(frozen=True)
class ResourceDecision:
    system_id: str
    resource_id: str
    category: Optional[str]
    evidence_id: str
    is_violation: bool
    violation_kind: str  # "remaining_record", "exposed_pii", "retained_missing", or ""
    remediation_op: str  # DELETE_RECORD/REDACT_RECORD/ANONYMIZE_RECORD, or "" if none applies
    final_state: str  # ABSENT/REDACTED/ANONYMIZED/PRESENT
    fallback_used: bool
    fallback_note: str


#: BACKUP_ARCHIVE is handled exclusively through the detector pathway
#: (code/audit/detectors.py's restore-risk finding, or a direct
#: VERIFY_RESTORE_BLOCKED when already compliant -- see
#: code/audit/case_runner.py). Measured on the samples: a compliant
#: backup is verified as VERIFY_RESTORE_BLOCKED only, never also a
#: generic VERIFY_RECORD_PRESENT for the archive record itself (e.g.
#: case_27's backup_5970 has exactly one verification step, not two).
#: ACTIVE_DATA_FLOW has no deletion_rules.csv row at all and was never
#: reachable through this policy pathway to begin with.
_DETECTOR_ONLY_CATEGORIES = {"BACKUP_ARCHIVE"}


def decide_for_resource(state: ResourceState, audit_at) -> Optional[ResourceDecision]:
    """Returns None for an unknown state (no evidence either way -- not
    reported, same evidence-grounded principle as D17), a category with
    no policy rule at all, or a detector-only category."""
    if state.exists is None:
        return None
    if state.category in _DETECTOR_ONLY_CATEGORIES:
        return None
    outcome = policy.evaluate(state, audit_at)
    if outcome is None:
        return None

    action = outcome.required_action
    category = state.category

    if action == "DELETE":
        if state.exists:
            return ResourceDecision(
                state.system_id, state.resource_id, category, state.evidence_id,
                True, "remaining_record", "DELETE_RECORD", "ABSENT", outcome.fallback_used, outcome.note,
            )
        return ResourceDecision(
            state.system_id, state.resource_id, category, state.evidence_id,
            False, "", "", "ABSENT", outcome.fallback_used, outcome.note,
        )

    if action in ("REDACT", "ANONYMIZE"):
        exposed = bool(state.identifiers_present) or policy.is_attributable(state)

        if state.exists:
            if exposed:
                return ResourceDecision(
                    state.system_id, state.resource_id, category, state.evidence_id,
                    True, "exposed_pii", _REMEDIATION_OP_BY_ACTION[action], _FINAL_STATE_BY_ACTION[action],
                    outcome.fallback_used, outcome.note,
                )
            return ResourceDecision(
                state.system_id, state.resource_id, category, state.evidence_id,
                False, "", "", _FINAL_STATE_BY_ACTION[action], outcome.fallback_used, outcome.note,
            )
        # exists == False
        if category in _ABSENCE_IS_VIOLATION_FOR_REDACT:
            return ResourceDecision(
                state.system_id, state.resource_id, category, state.evidence_id,
                True, "retained_missing", "", "PRESENT", outcome.fallback_used, outcome.note,
            )
        return ResourceDecision(
            state.system_id, state.resource_id, category, state.evidence_id,
            False, "", "", "ABSENT", outcome.fallback_used, outcome.note,
        )

    if action == "RETAIN":
        if not state.exists:
            return ResourceDecision(
                state.system_id, state.resource_id, category, state.evidence_id,
                True, "retained_missing", "", "PRESENT", outcome.fallback_used, outcome.note,
            )
        return ResourceDecision(
            state.system_id, state.resource_id, category, state.evidence_id,
            False, "", "", "PRESENT", outcome.fallback_used, outcome.note,
        )

    return None  # pragma: no cover


def decide_status(
    resource_decisions: list[ResourceDecision], active_flow_findings: list[Finding], restore_findings: list[Finding],
    is_deletion_intent: bool,
) -> str:
    """NOT_APPLICABLE if the request does not authorize deletion
    (placeholder in Phase 3: always True, real intent in Phase 4); any
    violation (resource or detector) -> INCOMPLETE; otherwise COMPLETE.
    reported_status is never consulted."""
    if not is_deletion_intent:
        return "NOT_APPLICABLE"
    if any(d.is_violation for d in resource_decisions):
        return "INCOMPLETE"
    if active_flow_findings or restore_findings:
        return "INCOMPLETE"
    return "COMPLETE"
