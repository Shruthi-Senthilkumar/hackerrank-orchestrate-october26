"""Orchestrates one case end to end: identity -> linking -> state ->
policy -> detectors -> decision -> planner. No model calls (Phase 3
scope); intent is a deterministic placeholder that always authorizes
deletion (real intent classification is Phase 4).
"""

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit import decision, detectors, identity, planner, state
    from audit.evidence.registry import (
        RegistryResult,
        visible_coverage,
        visible_document_hints,
        visible_observations,
        visible_trace_hints,
    )
    from audit.linker import link_observations
    from audit.loaders import DeletionRequest
    from audit.timeview import build_time_view
else:
    from . import decision, detectors, identity, planner, state
    from .evidence.registry import (
        RegistryResult,
        visible_coverage,
        visible_document_hints,
        visible_observations,
        visible_trace_hints,
    )
    from .linker import link_observations
    from .loaders import DeletionRequest
    from .timeview import build_time_view

# Phase 3 scope: intent is always deletion. Real classification is Phase 4.
DETERMINISTIC_INTENT_IS_DELETION = True


@dataclass
class CaseTrace:
    case_id: str
    identity_resolution: dict = field(default_factory=dict)
    linked_resources: list = field(default_factory=list)  # [{resource_id, rule, system_id}]
    resource_states: list = field(default_factory=list)  # [{resource_id, exists, evidence_id, as_of}]
    resource_decisions: list = field(default_factory=list)
    policy_fallbacks: list = field(default_factory=list)
    active_flow_findings: list = field(default_factory=list)
    restore_findings: list = field(default_factory=list)
    reported_status_claim: str = ""
    reported_at_claim: str = ""
    status: str = ""
    fallback_reason: str = ""


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list
    trace: CaseTrace


def _dominant_category(categories: list[Optional[str]]) -> Optional[str]:
    non_none = [c for c in categories if c]
    if not non_none:
        return None
    return Counter(non_none).most_common(1)[0][0]


def run_case(case: DeletionRequest, registry: RegistryResult) -> CaseResult:
    trace = CaseTrace(case_id=case.case_id, reported_status_claim=case.reported_status)

    resolution = identity.resolve_request_email(case.email, case.requested_at)
    trace.identity_resolution = {
        "user_id": resolution.user_id,
        "is_historical": resolution.is_historical,
        "is_ambiguous": resolution.is_ambiguous,
        "candidates": resolution.candidates,
    }

    if resolution.user_id is None:
        trace.status = "COMPLETE"
        trace.fallback_reason = "identity did not resolve; no person to audit, nothing to report"
        return CaseResult(case.case_id, "COMPLETE", [], trace)

    time_view = build_time_view(case.audit_at)
    ident = identity.build_identity(resolution.user_id, case.audit_at)

    obs = visible_observations(registry, time_view)
    trace_hints = visible_trace_hints(registry, time_view)
    doc_hints = visible_document_hints(registry, time_view)
    coverage = visible_coverage(registry, time_view)

    linked = link_observations(obs, ident, time_view, trace_hints, doc_hints)

    by_resource: dict[str, list] = {}
    for l in linked:
        by_resource.setdefault(l.observation.resource_id, []).append(l)
    trace.linked_resources = [
        {"resource_id": rid, "rule": entries[0].rule, "system_id": entries[0].observation.system_id}
        for rid, entries in sorted(by_resource.items())
    ]

    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    visible_obs_by_file = {
        fid: obs_list for fid, obs_list in registry.observations_by_file.items() if fid in visible_file_ids
    }

    group_categories = state.build_group_categories(registry.observations_by_file)
    group_shapes = state.build_group_shapes(registry.observations_by_file)
    person_linked_resource_ids = set(by_resource.keys())
    resource_states = []
    for rid, entries in by_resource.items():
        system_id = entries[0].observation.system_id
        category = _dominant_category([e.observation.category for e in entries])
        rs = state.compute_state(
            system_id, rid, category, visible_obs_by_file, coverage, case.audit_at,
            group_categories, group_shapes, person_linked_resource_ids,
        )
        resource_states.append(rs)
    trace.resource_states = [
        {"resource_id": s.resource_id, "exists": s.exists, "evidence_id": s.evidence_id,
         "as_of": s.as_of.isoformat() if s.as_of else None}
        for s in resource_states
    ]

    resource_decisions = []
    for s in resource_states:
        d = decision.decide_for_resource(s, case.audit_at)
        if d is not None:
            resource_decisions.append(d)
            if d.fallback_used:
                trace.policy_fallbacks.append(
                    {"resource_id": d.resource_id, "category": d.category, "note": d.fallback_note}
                )
    trace.resource_decisions = [
        {"resource_id": d.resource_id, "category": d.category, "is_violation": d.is_violation,
         "violation_kind": d.violation_kind, "final_state": d.final_state, "evidence_id": d.evidence_id}
        for d in resource_decisions
    ]

    flow_states = [s for s in resource_states if s.category == "ACTIVE_DATA_FLOW"]
    backup_states = [s for s in resource_states if s.category == "BACKUP_ARCHIVE"]
    active_flow_findings = detectors.strengthen_with_recreation(
        detectors.detect_active_data_flows(flow_states), time_view
    )
    restore_findings = detectors.strengthen_with_recreation(
        detectors.detect_restore_risks(backup_states), time_view
    )
    trace.active_flow_findings = [f.__dict__ for f in active_flow_findings]
    trace.restore_findings = [f.__dict__ for f in restore_findings]

    active_flow_ids = {f.resource_id for f in active_flow_findings}
    restore_risk_ids = {f.resource_id for f in restore_findings}
    compliant_flow_states = [s for s in flow_states if s.exists and s.resource_id not in active_flow_ids]
    compliant_backup_states = [s for s in backup_states if s.exists and s.resource_id not in restore_risk_ids]

    status = decision.decide_status(
        resource_decisions, active_flow_findings, restore_findings, DETERMINISTIC_INTENT_IS_DELETION
    )
    steps = planner.plan_steps(
        status, resource_decisions, active_flow_findings, restore_findings,
        compliant_flow_states, compliant_backup_states,
    )
    trace.status = status

    return CaseResult(case.case_id, status, steps, trace)
