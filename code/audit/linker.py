"""F06 resource linker (PRD 7.4).

An Observation belongs to a person iff, at audit_at:
(a) its link_keys contain the person's user_id, or an email/phone/hash
    in the person's identity set (both folded into link_keys by every
    parser already, since a record's own customer_reference/
    subject_reference/user_id and its email/phone/hash values all land
    in link_keys);
(b) a LINK_RESOURCE_IDENTITY activity visible at audit_at links the
    resource to the person's user_id or email;
(c) (Phase 2b) a log line sharing the SAME trace_id as this resource's
    own log line carries an identifier of the person, even though this
    resource's own line does not (e.g. a "profile_lookup_started" line
    has the lookup_key; the later "_completed" line in the same trace
    has the resource_id but no identifier of its own). Grounded in a
    real, generic relationship the data actually has -- a shared
    trace_id within one log file -- never an ID-number pattern or a
    time window. See code/audit/evidence/log_parser.py's TraceHint and
    its module docstring for which trace-like keys exist in this
    dataset (only `trace_id` is ever reused across lines) and which
    identifier-bearing keys were found (lookup_key, subject_ref/
    subject_key, correlation_key, match_key, or any email-shaped
    value). A trace hint whose own line falls after audit_at is
    ignored, even if its file is otherwise visible.
(d) (Phase 3 task 0) a free-text document (currently: PDFs) contains
    both a known resource-id shape (code/audit/mapping.py's prefixes)
    and an identifier of the person anywhere in its text, even if the
    specific resource mention itself has no identifier right next to
    it. Mirrors trace_correlation's mechanism exactly, grouped by
    document (file_id) instead of trace_id; see
    code/audit/evidence/pdf_parser.py's DocumentHint extraction. A
    document whose only identifier belongs to someone else never links.
(e) it is referenced by an already-linked resource (e.g. a search
    document's source_resource_id pointing at a linked account, or an
    export pointing at a search document) -- computed as a closure over
    shared link_key values.

A name alone never links (names are not in link_keys at all; see
code/audit/evidence/normalize.py, which stores a name as an identifier
flag and an attrs value, never as a link key).
"""

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.models import DocumentHint, Identity, Observation, TraceHint
    from audit.timeview import TimeView
else:
    from .models import DocumentHint, Identity, Observation, TraceHint
    from .timeview import TimeView

_LINK_ACTIVITY_RE = re.compile(
    r"(?:linked|confirmed)\s+(\S+)\s*\([^)]*\)\s*(?:to|belongs only to)\s+"
    r"([^\s]+@[^\s]+?)\s+and\s+(user_\d+)"
)

LinkRule = str  # "identity_key", "activity", "trace_correlation", "same_document", "reference_closure"


@dataclass(frozen=True)
class LinkedObservation:
    observation: Observation
    rule: LinkRule


def _activity_links_visible(time_view: TimeView) -> dict[str, tuple[str, str]]:
    """resource_id -> (email, user_id) for every LINK_RESOURCE_IDENTITY
    activity row visible at this TimeView's audit_at."""
    links: dict[str, tuple[str, str]] = {}
    for a in time_view.visible_activity():
        if a.event_type != "LINK_RESOURCE_IDENTITY":
            continue
        m = _LINK_ACTIVITY_RE.search(a.details)
        if not m:
            continue
        _alias, email, user_id = m.groups()
        links[a.resource_id] = (email.strip().lower(), user_id)
    return links


def _group_values_matching_identity(
    hints: list, identity_keys: set[str], group_id_attr: str
) -> dict[str, set[str]]:
    """group_id (trace_id or document_id) -> the subset of its hinted
    values that match this identity. Only groups with at least one
    matching value are kept, so an unrelated trace/document never has
    to be considered downstream."""
    by_group: dict[str, set[str]] = defaultdict(set)
    for hint in hints:
        value = hint.value if hint.value.startswith("user_") else hint.value.strip().lower()
        if value in identity_keys:
            by_group[getattr(hint, group_id_attr)].add(value)
    return by_group


def link_observations(
    observations: list[Observation],
    identity: Identity,
    time_view: TimeView,
    trace_hints: list[TraceHint] = (),
    document_hints: list[DocumentHint] = (),
) -> list[LinkedObservation]:
    identity_keys = {identity.user_id} | identity.emails | identity.phones | identity.hashes
    activity_links = _activity_links_visible(time_view)
    matching_traces = _group_values_matching_identity(list(trace_hints), identity_keys, "trace_id")
    matching_documents = _group_values_matching_identity(list(document_hints), identity_keys, "document_id")

    by_resource: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        if obs.resource_id:
            by_resource[obs.resource_id].append(obs)

    resource_keys: dict[str, set[str]] = {
        rid: set().union(*(o.link_keys for o in obs_list)) for rid, obs_list in by_resource.items()
    }
    resource_trace_ids: dict[str, set[str]] = {
        rid: {o.attrs["trace_id"] for o in obs_list if o.attrs.get("trace_id")}
        for rid, obs_list in by_resource.items()
    }
    resource_source_ids: dict[str, set[str]] = {
        rid: {o.source_id for o in obs_list} for rid, obs_list in by_resource.items()
    }

    rule_by_resource: dict[str, LinkRule] = {}
    for rid, keys in resource_keys.items():
        if keys & identity_keys:
            rule_by_resource[rid] = "identity_key"
            continue
        link = activity_links.get(rid)
        if link and (link[0] in identity_keys or link[1] == identity.user_id):
            rule_by_resource[rid] = "activity"
            continue
        if resource_trace_ids.get(rid, set()) & matching_traces.keys():
            rule_by_resource[rid] = "trace_correlation"
            continue
        if resource_source_ids.get(rid, set()) & matching_documents.keys():
            rule_by_resource[rid] = "same_document"

    # closure: anything referenced by (sharing a link key with) an already
    # linked resource is linked too, via the "reference_closure" rule.
    key_to_resources: dict[str, set[str]] = defaultdict(set)
    for rid, keys in resource_keys.items():
        for key in keys:
            key_to_resources[key].add(rid)

    frontier = list(rule_by_resource.keys())
    while frontier:
        rid = frontier.pop()
        for key in resource_keys.get(rid, set()):
            for neighbor in key_to_resources.get(key, set()):
                if neighbor not in rule_by_resource:
                    rule_by_resource[neighbor] = "reference_closure"
                    frontier.append(neighbor)

    linked: list[LinkedObservation] = []
    for rid, rule in rule_by_resource.items():
        for obs in by_resource[rid]:
            linked.append(LinkedObservation(observation=obs, rule=rule))
    return linked
