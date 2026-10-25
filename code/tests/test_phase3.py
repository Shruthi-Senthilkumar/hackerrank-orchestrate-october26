"""Phase 3 test suite: state at audit_at, policy predicates, detectors,
decision, planner ordering, output validator/writer, determinism.

Uses only synthetic fixtures (never real dataset IDs as hardcoded
expectations) to isolate each unit's own logic from the real dataset's
specific content.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import decision, detectors, planner, policy, state  # noqa: E402
from audit.models import Coverage, Observation  # noqa: E402
from audit.output import serialize_steps, validate_row, write_output_csv  # noqa: E402


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def obs(resource_id, exists, observed_at, store="store_a", category="USER_PROFILE",
        system_id="account_service", source_id="evidence_1", attrs=None, identifiers_present=frozenset()):
    return Observation(
        system_id=system_id, resource_id=resource_id, category=category, store=store,
        source_id=source_id, manifest_time=observed_at, observed_at=observed_at,
        exists=exists, identifiers_present=identifiers_present, attrs=attrs or {},
    )


def cov(store, observed_at, source_id, scoped=False, collection="col"):
    return Coverage(store=store, collection=collection, observed_at=observed_at, source_id=source_id, scoped=scoped)


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------

def test_state_later_snapshot_wins():
    observations = {
        "ev_1": [obs("r1", True, dt("2026-01-01T00:00:00+00:00"), source_id="ev_1")],
        "ev_2": [obs("r1", False, dt("2026-06-01T00:00:00+00:00"), source_id="ev_2")],
    }
    result = state.compute_state("account_service", "r1", "USER_PROFILE", observations, [], dt("2026-12-01T00:00:00+00:00"))
    assert result.exists is False
    assert result.evidence_id == "ev_2"


def test_state_ignores_facts_after_audit_at():
    observations = {
        "ev_1": [obs("r1", True, dt("2026-01-01T00:00:00+00:00"), source_id="ev_1")],
        "ev_2": [obs("r1", False, dt("2026-06-01T00:00:00+00:00"), source_id="ev_2")],
    }
    # audit_at is before the later "absent" fact -- must not see the future.
    result = state.compute_state("account_service", "r1", "USER_PROFILE", observations, [], dt("2026-03-01T00:00:00+00:00"))
    assert result.exists is True
    assert result.evidence_id == "ev_1"


def test_state_replica_drift_present_wins():
    t = dt("2026-01-01T00:00:00+00:00")
    observations = {
        "ev_1": [
            obs("r1", False, t, store="customer_data_primary", source_id="ev_1"),
            obs("r1", True, t, store="customer_data_read_replica", source_id="ev_1"),
        ],
    }
    result = state.compute_state("account_service", "r1", "USER_PROFILE", observations, [], dt("2026-12-01T00:00:00+00:00"))
    assert result.exists is True


def test_state_coverage_based_absence():
    t = dt("2026-01-01T00:00:00+00:00")
    # "foo_other" shares foo_'s resource_id shape with "foo_r1" so the
    # shape-match gate (resource_id_shape) does not itself block this.
    observations = {"ev_1": [obs("foo_other", True, t, store="store_a", category="USER_PROFILE", source_id="ev_1")]}
    coverage = [cov("store_a", t, "ev_1")]
    group_categories = state.build_group_categories(observations)
    group_shapes = state.build_group_shapes(observations)
    result = state.compute_state(
        "account_service", "foo_r1", "USER_PROFILE", observations, coverage, dt("2026-12-01T00:00:00+00:00"),
        group_categories, group_shapes,
    )
    assert result.exists is False
    assert result.evidence_id == "ev_1"


def test_state_coverage_absence_requires_category_match():
    """A store that only ever holds a DIFFERENT category must never
    prove this resource absent, even if it is Coverage-backed."""
    t = dt("2026-01-01T00:00:00+00:00")
    observations = {"ev_1": [obs("other_resource", True, t, store="store_a", category="SEARCH_INDEX_ENTRY", source_id="ev_1")]}
    coverage = [cov("store_a", t, "ev_1")]
    group_categories = state.build_group_categories(observations)
    group_shapes = state.build_group_shapes(observations)
    result = state.compute_state(
        "account_service", "r1", "USER_PROFILE", observations, coverage, dt("2026-12-01T00:00:00+00:00"),
        group_categories, group_shapes,
    )
    assert result.exists is None  # unknown, not absent


def test_state_coverage_absence_requires_degenerate_file_excluded():
    """A file with zero observations anywhere (a failed/degenerate
    capture) must never be trusted to prove absence, even with a
    Coverage record naming the right store."""
    t = dt("2026-01-01T00:00:00+00:00")
    observations: dict = {}  # degenerate: no observations in this file at all
    coverage = [cov("store_a", t, "ev_1")]
    result = state.compute_state(
        "account_service", "r1", "USER_PROFILE", observations, coverage, dt("2026-12-01T00:00:00+00:00"),
        {"store_a": {"USER_PROFILE"}}, {"store_a": {"account_"}},
    )
    assert result.exists is None


def test_state_scoped_coverage_requires_other_linked_resource():
    t = dt("2026-01-01T00:00:00+00:00")
    observations = {"ev_1": [obs("someone_elses_resource", True, t, store="bundle", category="USER_PROFILE", source_id="ev_1")]}
    coverage = [cov("bundle", t, "ev_1", scoped=True)]
    group_categories = state.build_group_categories(observations)
    group_shapes = state.build_group_shapes(observations)
    # no person_linked_resource_ids passed -> scoped coverage proves nothing
    result = state.compute_state(
        "account_service", "r1", "USER_PROFILE", observations, coverage, dt("2026-12-01T00:00:00+00:00"),
        group_categories, group_shapes, person_linked_resource_ids=set(),
    )
    assert result.exists is None

    # same bundle, but this person DOES have another resource in it
    observations2 = {"ev_1": [obs("r2", True, t, store="bundle", category="USER_PROFILE", source_id="ev_1")]}
    group_categories2 = state.build_group_categories(observations2)
    group_shapes2 = state.build_group_shapes(observations2)
    result2 = state.compute_state(
        "account_service", "r1", "USER_PROFILE", observations2, coverage, dt("2026-12-01T00:00:00+00:00"),
        group_categories2, group_shapes2, person_linked_resource_ids={"r2"},
    )
    assert result2.exists is False


def test_state_scoped_group_does_not_leak_across_unrelated_sub_collection():
    """One bundle FILE can embed both this person's own scoped
    collection and an unrelated, comprehensive sub-collection (a
    different store_group) that happens to tag entries with the same
    category/shape but never mentions this person at all. The unrelated
    sub-collection's coverage must not "prove" this person's resource
    absent just because the FILE as a whole does mention them (via a
    different group) -- the check must be scoped to the SAME group."""
    t = dt("2026-01-01T00:00:00+00:00")
    observations = {
        "ev_1": [
            # this person's own resource, in their own group ("mine")
            obs("foo_mine", True, t, store="mine", category="SEARCH_INDEX_ENTRY", source_id="ev_1"),
            # an unrelated comprehensive sub-collection in the SAME file,
            # under a different group, that never mentions this person
            obs("foo_someone_else", True, t, store="other_bundle_group", category="SEARCH_INDEX_ENTRY", source_id="ev_1"),
        ],
    }
    coverage = [cov("other_bundle_group", t, "ev_1", scoped=True, collection="unrelated_history")]
    group_categories = state.build_group_categories(observations)
    group_shapes = state.build_group_shapes(observations)
    result = state.compute_state(
        "search_service", "foo_target", "SEARCH_INDEX_ENTRY", observations, coverage,
        dt("2026-12-01T00:00:00+00:00"), group_categories, group_shapes,
        person_linked_resource_ids={"foo_mine"},
    )
    # The unrelated group's coverage must not apply: no fact at all for
    # foo_target (unknown, not wrongly absent).
    assert result.exists is None


def test_state_tie_break_on_source_id_is_deterministic():
    """Two facts with the EXACT same observed_at must resolve the same
    way regardless of dict/set iteration order (PYTHONHASHSEED)."""
    t = dt("2026-01-01T00:00:00+00:00")
    observations = {
        "ev_a": [obs("r1", True, t, store="store_a", source_id="ev_a")],
        "ev_b": [obs("r1", False, t, store="store_b", source_id="ev_b")],
    }
    result1 = state.compute_state("sys", "r1", "USER_PROFILE", observations, [], dt("2026-12-01T00:00:00+00:00"))
    # Re-run with the dict rebuilt in the opposite insertion order --
    # the result must be identical either way.
    observations_reordered = {"ev_b": observations["ev_b"], "ev_a": observations["ev_a"]}
    result2 = state.compute_state("sys", "r1", "USER_PROFILE", observations_reordered, [], dt("2026-12-01T00:00:00+00:00"))
    assert result1.exists == result2.exists
    assert result1.evidence_id == result2.evidence_id


def test_state_no_evidence_is_unknown():
    result = state.compute_state("account_service", "r1", "USER_PROFILE", {}, [], dt("2026-12-01T00:00:00+00:00"))
    assert result.exists is None
    assert result.evidence_id == ""


# ---------------------------------------------------------------------------
# policy.py predicates
# ---------------------------------------------------------------------------

def _state(category, attrs=None, identifiers_present=frozenset(), exists=True):
    return state.ResourceState(
        system_id="sys", resource_id="r1", category=category, exists=exists,
        evidence_id="ev_1", as_of=dt("2026-01-01T00:00:00+00:00"), attrs=attrs or {},
        identifiers_present=identifiers_present,
    )


def test_predicate_shared_context_true_with_message():
    s = _state("SUPPORT_MESSAGE", attrs={"message_text": "Customer contacted support."})
    result, fallback, _ = policy.predicate_shared_context(s)
    assert result is True and fallback is False


def test_predicate_shared_context_fallback_without_message():
    s = _state("SUPPORT_MESSAGE", attrs={})
    result, fallback, _ = policy.predicate_shared_context(s)
    assert result is True and fallback is True


def test_predicate_within_retention_future_date_retains():
    s = _state("SECURITY_AUDIT_LOG", attrs={"retention_until": "2099-01-01T00:00:00Z"})
    result, fallback, _ = policy.predicate_within_retention(s, dt("2026-01-01T00:00:00+00:00"))
    assert result is True and fallback is False


def test_predicate_within_retention_past_date_deletes():
    s = _state("SECURITY_AUDIT_LOG", attrs={"retention_until": "2020-01-01T00:00:00Z"})
    result, fallback, _ = policy.predicate_within_retention(s, dt("2026-01-01T00:00:00+00:00"))
    assert result is False and fallback is False


def test_predicate_within_retention_missing_falls_back_to_retain():
    s = _state("SECURITY_AUDIT_LOG", attrs={})
    result, fallback, note = policy.predicate_within_retention(s, dt("2026-01-01T00:00:00+00:00"))
    assert result is True and fallback is True
    assert "RETAIN" in note


def test_predicate_legal_hold_active_missing_falls_back_to_retain():
    s = _state("LEGAL_HOLD_RECORD", attrs={})
    result, fallback, _ = policy.predicate_legal_hold_active(s, dt("2026-01-01T00:00:00+00:00"))
    assert result is True and fallback is True


def test_predicate_legal_hold_expired():
    s = _state("LEGAL_HOLD_RECORD", attrs={"retained_until": "2020-01-01T00:00:00Z"})
    result, fallback, _ = policy.predicate_legal_hold_active(s, dt("2026-01-01T00:00:00+00:00"))
    assert result is False and fallback is False


def test_predicate_tombstone_compliant_true_when_clean():
    s = _state("ACCOUNT_TOMBSTONE", attrs={})
    result, _, _ = policy.predicate_tombstone_compliant(s)
    assert result is True


def test_predicate_tombstone_compliant_false_with_identifier():
    s = _state("ACCOUNT_TOMBSTONE", attrs={"email": "person@example.com"})
    result, _, _ = policy.predicate_tombstone_compliant(s)
    assert result is False


def test_policy_evaluate_unconditional_category():
    s = _state("USER_PROFILE")
    outcome = policy.evaluate(s, dt("2026-01-01T00:00:00+00:00"))
    assert outcome is not None
    assert outcome.predicate_name == "always"


def test_policy_evaluate_unknown_category_returns_none():
    s = _state("NOT_A_REAL_CATEGORY")
    assert policy.evaluate(s, dt("2026-01-01T00:00:00+00:00")) is None


# ---------------------------------------------------------------------------
# detectors.py
# ---------------------------------------------------------------------------

def test_detect_active_data_flows_only_when_enabled():
    enabled = _state("ACTIVE_DATA_FLOW", attrs={"enabled": "true"}, exists=True)
    disabled = _state("ACTIVE_DATA_FLOW", attrs={"enabled": "false"}, exists=True)
    findings = detectors.detect_active_data_flows([enabled, disabled])
    assert len(findings) == 1
    assert findings[0].resource_id == "r1"


def test_detect_restore_risks_restore_allowed_field():
    risky = _state("BACKUP_ARCHIVE", attrs={"restore_allowed": "true"}, exists=True)
    safe = _state("BACKUP_ARCHIVE", attrs={"restore_allowed": "false"}, exists=True)
    findings = detectors.detect_restore_risks([risky, safe])
    assert len(findings) == 1


def test_detect_restore_risks_eligible_field_fallback():
    """log vocabulary uses eligible=true instead of restore_allowed."""
    risky = _state("BACKUP_ARCHIVE", attrs={"eligible": "true", "deletion_block": "false"}, exists=True)
    findings = detectors.detect_restore_risks([risky])
    assert len(findings) == 1


def test_detect_restore_risks_decoy_not_restorable():
    not_risky = _state("BACKUP_ARCHIVE", attrs={}, exists=True)
    findings = detectors.detect_restore_risks([not_risky])
    assert findings == []


# ---------------------------------------------------------------------------
# decision.py
# ---------------------------------------------------------------------------

def test_decide_for_resource_delete_violation_when_exists():
    s = _state("USER_PROFILE", exists=True)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    assert d.is_violation is True
    assert d.remediation_op == "DELETE_RECORD"


def test_decide_for_resource_delete_compliant_when_absent():
    s = _state("USER_PROFILE", exists=False)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    assert d.is_violation is False


def test_decide_for_resource_unknown_state_returns_none():
    s = _state("USER_PROFILE", exists=None)
    assert decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00")) is None


def test_decide_for_resource_backup_archive_is_detector_only():
    s = _state("BACKUP_ARCHIVE", exists=True)
    assert decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00")) is None


def test_decide_status_not_applicable_when_no_intent():
    assert decision.decide_status([], [], [], False) == "NOT_APPLICABLE"


def test_decide_status_complete_when_no_violations():
    assert decision.decide_status([], [], [], True) == "COMPLETE"


def test_decide_status_incomplete_on_violation():
    s = _state("USER_PROFILE", exists=True)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    assert decision.decide_status([d], [], [], True) == "INCOMPLETE"


def test_decide_status_incomplete_on_active_flow_finding():
    enabled = _state("ACTIVE_DATA_FLOW", attrs={"enabled": "true"}, exists=True)
    findings = detectors.detect_active_data_flows([enabled])
    assert decision.decide_status([], findings, [], True) == "INCOMPLETE"


# ---------------------------------------------------------------------------
# planner.py
# ---------------------------------------------------------------------------

def test_planner_not_applicable_is_empty():
    assert planner.plan_steps("NOT_APPLICABLE", [], [], []) == []


def test_planner_phase_order_finding_remediation_verification():
    s = _state("USER_PROFILE", exists=True)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    steps = planner.plan_steps("INCOMPLETE", [d], [], [])
    phases = [s["phase"] for s in steps]
    assert phases == sorted(phases, key=lambda p: planner.PHASE_ORDER[p])
    assert phases[0] == "FINDING"
    assert phases[-1] == "VERIFICATION"


def test_planner_step_numbers_consecutive_from_one():
    s = _state("USER_PROFILE", exists=True)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    steps = planner.plan_steps("INCOMPLETE", [d], [], [])
    assert [s["step_no"] for s in steps] == list(range(1, len(steps) + 1))


def test_planner_disable_before_delete():
    """AGENTS.md 6.5: disable flows before changing dependent records."""
    flow_state = _state("ACTIVE_DATA_FLOW", attrs={"enabled": "true"}, exists=True)
    flow_finding = detectors.detect_active_data_flows([flow_state])
    profile_state = _state("USER_PROFILE", exists=True)
    profile_decision = decision.decide_for_resource(profile_state, dt("2026-01-01T00:00:00+00:00"))
    steps = planner.plan_steps("INCOMPLETE", [profile_decision], flow_finding, [])
    remediation_ops = [s["operation"] for s in steps if s["phase"] == "REMEDIATION"]
    assert remediation_ops.index("DISABLE_DATA_FLOW") < remediation_ops.index("DELETE_RECORD")


def test_planner_complete_only_has_verification():
    s = _state("USER_PROFILE", exists=False)
    d = decision.decide_for_resource(s, dt("2026-01-01T00:00:00+00:00"))
    steps = planner.plan_steps("COMPLETE", [d], [], [])
    assert all(s["phase"] == "VERIFICATION" for s in steps)
    assert all(s["evidence_id"] != "" for s in steps)


# ---------------------------------------------------------------------------
# output.py validator / writer
# ---------------------------------------------------------------------------

_VISIBLE_EV = "evidence_in_dataset"


def _valid_finding_step(evidence_id=_VISIBLE_EV):
    return {"step_no": 1, "phase": "FINDING", "system_id": "sys", "resource_id": "r1",
            "operation": "REPORT_REMAINING_RECORD", "state": "PRESENT", "evidence_id": evidence_id}


def test_validate_row_not_applicable_requires_empty_steps():
    assert validate_row("case_x", "NOT_APPLICABLE", [], dt("2026-01-01T00:00:00+00:00")).ok
    assert not validate_row("case_x", "NOT_APPLICABLE", [_valid_finding_step()], dt("2026-01-01T00:00:00+00:00")).ok


def test_validate_row_invalid_status_rejected():
    assert not validate_row("case_x", "BOGUS", [], dt("2026-01-01T00:00:00+00:00")).ok


def test_validate_row_rejects_missing_field(monkeypatch):
    def fake_visible(_audit_at):
        return {_VISIBLE_EV}
    monkeypatch.setattr("audit.output._visible_evidence_ids", fake_visible)
    step = _valid_finding_step()
    del step["evidence_id"]
    result = validate_row("case_x", "INCOMPLETE", [step], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_non_consecutive_step_no(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    s1 = _valid_finding_step()
    s2 = _valid_finding_step()
    s2["step_no"] = 3
    result = validate_row("case_x", "INCOMPLETE", [s1, s2], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_phase_out_of_order(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    s1 = {"step_no": 1, "phase": "VERIFICATION", "system_id": "sys", "resource_id": "r1",
          "operation": "VERIFY_RECORD_ABSENT", "state": "ABSENT", "evidence_id": ""}
    s2 = _valid_finding_step()
    s2["step_no"] = 2
    result = validate_row("case_x", "INCOMPLETE", [s1, s2], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_op_not_allowed_in_phase(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    bad = _valid_finding_step()
    bad["operation"] = "DELETE_RECORD"  # a remediation op in a FINDING step
    result = validate_row("case_x", "INCOMPLETE", [bad], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_state_mismatched_with_op(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    bad = _valid_finding_step()
    bad["state"] = "ABSENT"  # REPORT_REMAINING_RECORD must be PRESENT
    result = validate_row("case_x", "INCOMPLETE", [bad], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_remediation_with_nonempty_evidence(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    bad = {"step_no": 1, "phase": "REMEDIATION", "system_id": "sys", "resource_id": "r1",
           "operation": "DELETE_RECORD", "state": "ABSENT", "evidence_id": _VISIBLE_EV}
    result = validate_row("case_x", "INCOMPLETE", [bad], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_finding_with_empty_evidence(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    bad = _valid_finding_step(evidence_id="")
    result = validate_row("case_x", "INCOMPLETE", [bad], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_rejects_unknown_evidence_id(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    bad = _valid_finding_step(evidence_id="not_a_real_evidence_id")
    result = validate_row("case_x", "INCOMPLETE", [bad], dt("2026-01-01T00:00:00+00:00"))
    assert not result.ok


def test_validate_row_accepts_wellformed(monkeypatch):
    monkeypatch.setattr("audit.output._visible_evidence_ids", lambda _a: {_VISIBLE_EV})
    result = validate_row("case_x", "INCOMPLETE", [_valid_finding_step()], dt("2026-01-01T00:00:00+00:00"))
    assert result.ok, result.errors


def test_serialize_steps_is_valid_json_array():
    steps = [_valid_finding_step()]
    text = serialize_steps(steps)
    parsed = json.loads(text)
    assert isinstance(parsed, list)
    assert parsed[0]["step_no"] == 1


def test_serialize_steps_deterministic():
    steps = [_valid_finding_step()]
    assert serialize_steps(steps) == serialize_steps(steps)


def test_write_output_csv_lf_no_bom(tmp_path):
    path = tmp_path / "output.csv"
    write_output_csv([("case_1", "COMPLETE", "[]")], path)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    assert b"\r\n" not in raw  # LF only
    assert raw.endswith(b"\n")


def test_write_output_csv_header_and_rows(tmp_path):
    path = tmp_path / "output.csv"
    write_output_csv([("case_2", "INCOMPLETE", "[]"), ("case_1", "COMPLETE", "[]")], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "case_id,deletion_status,steps_json"
    assert lines[1] == "case_2,INCOMPLETE,[]"
    assert lines[2] == "case_1,COMPLETE,[]"
