"""Final-phase task 5: at least three custom evaluation cases authored
by hand, as synthetic module-level inputs (no dataset files). Each
exercises the policy/decision/planner pipeline directly against a
constructed ResourceState set, matching the real contract's rules.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import decision, detectors, planner, state  # noqa: E402

AUDIT_AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _state(system_id, resource_id, category, exists, attrs=None, evidence_id="ev_1"):
    return state.ResourceState(
        system_id=system_id, resource_id=resource_id, category=category, exists=exists,
        evidence_id=evidence_id, as_of=AUDIT_AT, attrs=attrs or {}, identifiers_present=frozenset(),
    )


def test_custom_a_replica_drift_incomplete():
    """(a) A profile exists on a replica the primary snapshot lacks
    (replica drift). USER_PROFILE must still be DELETE -> INCOMPLETE."""
    s = _state("account_service", "account_c1", "USER_PROFILE", exists=True)
    d = decision.decide_for_resource(s, AUDIT_AT)
    assert d.is_violation is True
    steps = planner.plan_steps("INCOMPLETE", [d], [], [])
    assert any(s["operation"] == "REPORT_REMAINING_RECORD" for s in steps)
    assert any(s["operation"] == "DELETE_RECORD" for s in steps)
    assert any(s["operation"] == "VERIFY_RECORD_ABSENT" for s in steps)


def test_custom_b_tombstone_audit_analytics_complete():
    """(b) A redacted tombstone (no direct identifier), a retained
    security audit record within retention, and an anonymized
    analytics record (no longer attributable) -- all compliant ->
    COMPLETE, verification-only steps citing the covering evidence."""
    tombstone = _state("account_service", "tombstone_c1", "ACCOUNT_TOMBSTONE", exists=True, attrs={})
    audit_log = _state(
        "security_service", "audit_record_c1", "SECURITY_AUDIT_LOG", exists=True,
        attrs={"retention_until": "2099-01-01T00:00:00Z"},
    )
    # Already anonymized/removed: no longer attributable (rule_07/08),
    # and already absent -> compliant, not a violation.
    analytics = _state("analytics_platform", "analytics_c1", "ANALYTICS_PROFILE", exists=False, attrs={})

    decisions = [decision.decide_for_resource(s, AUDIT_AT) for s in (tombstone, audit_log, analytics)]
    assert all(d is not None and d.is_violation is False for d in decisions)

    status = decision.decide_status(decisions, [], [], True)
    assert status == "COMPLETE"
    steps = planner.plan_steps(status, decisions, [], [])
    ops = {s["operation"] for s in steps}
    assert ops == {"VERIFY_RECORD_REDACTED", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_ABSENT"}
    assert all(s["evidence_id"] for s in steps)  # COMPLETE: every step cites real evidence


def test_custom_c_active_flow_and_restorable_backup_remediation_order():
    """(c) An active data flow plus a restore-allowed backup, plus a
    dependent USER_PROFILE record -- remediation must disable the flow
    and block the restore BEFORE the dependent record is deleted, and
    verification must cover all three."""
    flow = _state("integration_service", "data_flow_c1", "ACTIVE_DATA_FLOW", exists=True, attrs={"enabled": "true"})
    backup = _state("backup_service", "backup_c1", "BACKUP_ARCHIVE", exists=True, attrs={"restore_allowed": "true"})
    profile = _state("account_service", "account_c2", "USER_PROFILE", exists=True)

    flow_findings = detectors.detect_active_data_flows([flow])
    restore_findings = detectors.detect_restore_risks([backup])
    profile_decision = decision.decide_for_resource(profile, AUDIT_AT)

    status = decision.decide_status([profile_decision], flow_findings, restore_findings, True)
    assert status == "INCOMPLETE"

    steps = planner.plan_steps(status, [profile_decision], flow_findings, restore_findings)
    remediation_ops = [s["operation"] for s in steps if s["phase"] == "REMEDIATION"]
    assert remediation_ops.index("DISABLE_DATA_FLOW") < remediation_ops.index("DELETE_RECORD")
    assert remediation_ops.index("BLOCK_RESTORE") < remediation_ops.index("DELETE_RECORD")
    verify_ops = {s["operation"] for s in steps if s["phase"] == "VERIFICATION"}
    assert verify_ops == {"VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED", "VERIFY_RECORD_ABSENT"}


def test_custom_d_non_deletion_request_is_not_applicable():
    """Optional fourth case: a non-deletion intent must short-circuit
    to NOT_APPLICABLE with steps=[], regardless of any resource state."""
    status = decision.decide_status([], [], [], False)
    assert status == "NOT_APPLICABLE"
    assert planner.plan_steps(status, [], [], []) == []
