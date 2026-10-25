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
(e) (Phase 3b rewrite) it is EXPLICITLY, DIRECTEDLY referenced by an
    already-linked resource via a `*_resource_id`-shaped field (never
    the bare `resource_id` itself) whose value has a recognized
    code/audit/mapping.py prefix shape -- e.g. the real
    `search_documents_primary.source_resource_id` column pointing at an
    account. This is code/audit/models.py's `Observation.references`,
    populated only by code/audit/evidence/normalize.py's
    classify_record. ONE hop only (REFERENCE_CLOSURE_MAX_HOPS below):
    the target is never itself used as a new source. Two more guards
    apply before a reference is trusted:
      - hub guard: if the SAME target is referenced by source resources
        that themselves carry more than one DISTINCT identity value
        (email/phone/hash/user_id -- never a resource id), the target is
        a hub (e.g. a shared cohort/region/status value that coincides
        with many unrelated people) and is never linked, for anyone.
      - conflicting-identity guard: if the target itself already carries
        an identity value that is NOT in the current person's identity
        set, it visibly belongs to someone else and is never linked to
        this person, even with no hub and no other guard involved.
    This REPLACES the earlier any-shared-key transitive closure (Phase
    3), which also matched through emails, phones, hashes, user_ids,
    customer_reference/subject_reference, and even a parser artifact
    (the literal text "null" standing in for an absent log field --
    fixed separately in code/audit/evidence/log_parser.py) -- diagnosed
    on case_51/case_77, where that shared-key closure had pulled in 88
    and 76 resources respectively, including one resource
    (account_3785) linked to BOTH of two different, unrelated people.

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
    from audit import mapping
    from audit.models import DocumentHint, Identity, Observation, TraceHint
    from audit.timeview import TimeView
else:
    from . import mapping
    from .models import DocumentHint, Identity, Observation, TraceHint
    from .timeview import TimeView

#: Phase 3b: reference_closure bridges exactly one hop from an already
#: (non-reference-closure) linked resource to the resource it explicitly
#: references. The target's own references are never followed further.
REFERENCE_CLOSURE_MAX_HOPS = 1

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
    # Phase 3b: cloud_runtime_export's own correlation key is named
    # `requestId`, not `trace_id` (see code/audit/evidence/log_parser.py's
    # module docstring) -- fall back to it exactly like the TraceHint
    # side already does, so a resource-bearing line from that family can
    # still be found via its own correlation key.
    resource_trace_ids: dict[str, set[str]] = {
        rid: {
            o.attrs["trace_id"] if o.attrs.get("trace_id") else o.attrs["requestId"]
            for o in obs_list
            if o.attrs.get("trace_id") or o.attrs.get("requestId")
        }
        for rid, obs_list in by_resource.items()
    }
    resource_source_ids: dict[str, set[str]] = {
        rid: {o.source_id for o in obs_list} for rid, obs_list in by_resource.items()
    }
    resource_references: dict[str, set[str]] = {
        rid: set().union(*(o.references for o in obs_list)) for rid, obs_list in by_resource.items()
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

    # reference_closure: exactly one directed hop from a resource ALREADY
    # linked by one of the rules above (never from another
    # reference_closure hit -- see REFERENCE_CLOSURE_MAX_HOPS) to a
    # resource it explicitly references. `resource_identity_values` is
    # each resource's OWN identity-shaped link keys -- everything except
    # its own id and anything shaped like a resource id -- used by both
    # guards below; a resource with no identity value of its own (the
    # common, intended case) has an empty set here, which is harmless.
    def _identity_values(rid: str) -> set[str]:
        return {v for v in resource_keys.get(rid, set()) if v != rid and not mapping.prefix_for_resource_id(v)}

    resource_identity_values = {rid: _identity_values(rid) for rid in resource_keys}

    # Hub guard: a target referenced by sources that carry more than one
    # DISTINCT identity value is ambiguous (a cohort/region/status-like
    # value that happens to coincide with many unrelated people, or
    # several different people's resources pointing at the same place)
    # and is never linked via reference_closure, for anyone.
    sources_by_target: dict[str, set[str]] = defaultdict(set)
    for rid, targets in resource_references.items():
        for target in targets:
            sources_by_target[target].add(rid)
    hub_targets = {
        target
        for target, sources in sources_by_target.items()
        if len(set().union(*(resource_identity_values.get(s, set()) for s in sources))) > 1
    }

    directly_linked = list(rule_by_resource.keys())
    for rid in directly_linked:
        for target in resource_references.get(rid, set()):
            if target in rule_by_resource or target not in resource_keys:
                continue
            if target in hub_targets:
                continue
            # Conflicting-identity guard: the target already visibly
            # belongs to someone else (an identity value that is not in
            # THIS person's identity set) -- never link it to this
            # person even though no hub is involved.
            if resource_identity_values.get(target, set()) - identity_keys:
                continue
            rule_by_resource[target] = "reference_closure"

    linked: list[LinkedObservation] = []
    for rid, rule in rule_by_resource.items():
        for obs in by_resource[rid]:
            linked.append(LinkedObservation(observation=obs, rule=rule))
    return linked
