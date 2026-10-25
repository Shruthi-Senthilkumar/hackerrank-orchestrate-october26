"""F09 detectors (PRD 7.6): active data flow, restore risk, recreation.

Each detector takes the already-linked ResourceStates for the relevant
category and returns Finding objects with the evidence id (or activity
id) that proves the condition. Activity rows alone never create a
finding by themselves (recreation only strengthens an existing
file-proven finding and is recorded for the trace, per the task's own
instruction); every Finding here cites file-based evidence.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.state import ResourceState
    from audit.timeview import TimeView
else:
    from .state import ResourceState
    from .timeview import TimeView


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Finding:
    kind: str  # "active_flow" or "restore_risk"
    system_id: str
    resource_id: str
    evidence_id: str
    recreation_activity_id: str = ""  # corroborating only; never the sole proof


def detect_active_data_flows(flow_states: list[ResourceState]) -> list[Finding]:
    findings = []
    for state in flow_states:
        if state.exists and _truthy(state.attrs.get("enabled")):
            findings.append(Finding("active_flow", state.system_id, state.resource_id, state.evidence_id))
    return findings


def _restore_allowed(attrs: dict) -> bool:
    """restore_allowed is the SQL/JSON field name. The log vocabulary
    (event=restore_candidate_evaluated) instead uses eligible/
    deletion_block -- surveyed across every occurrence in the 26 logs,
    always eligible=true deletion_block=false together, matching the
    known backup_4978 restore-risk finding -- so eligible=true is an
    equivalent signal, never a guess."""
    if "restore_allowed" in attrs:
        return _truthy(attrs.get("restore_allowed"))
    if "eligible" in attrs:
        return _truthy(attrs.get("eligible"))
    return False


def detect_restore_risks(backup_states: list[ResourceState]) -> list[Finding]:
    findings = []
    for state in backup_states:
        if state.exists and _restore_allowed(state.attrs):
            findings.append(Finding("restore_risk", state.system_id, state.resource_id, state.evidence_id))
    return findings


_RECREATION_EVENT_TYPES = {"SYNC_RECORD", "RESTORE_BACKUP"}


def strengthen_with_recreation(findings: list[Finding], time_view: TimeView) -> list[Finding]:
    """For each finding, looks for a visible SYNC_RECORD/RESTORE_BACKUP
    activity row targeting the same resource_id, after the file
    evidence's own as_of time, with the source flow/backup already
    known active (the finding only exists because the file evidence
    already proved enabled=1/restore_allowed=1). Recreation activity by
    itself never creates a finding; it only adds a corroborating
    activity id for the trace."""
    activity_by_resource: dict[str, list] = {}
    for a in time_view.visible_activity():
        if a.event_type in _RECREATION_EVENT_TYPES:
            activity_by_resource.setdefault(a.resource_id, []).append(a)

    strengthened = []
    for f in findings:
        matches = activity_by_resource.get(f.resource_id, [])
        activity_id = max(matches, key=lambda a: a.event_time).activity_id if matches else ""
        strengthened.append(
            Finding(f.kind, f.system_id, f.resource_id, f.evidence_id, recreation_activity_id=activity_id)
        )
    return strengthened
