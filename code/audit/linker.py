"""F06 resource linker (PRD 7.4).

An Observation belongs to a person iff, at audit_at:
(a) its link_keys contain the person's user_id, or an email/phone/hash
    in the person's identity set (both folded into link_keys by every
    parser already, since a record's own customer_reference/
    subject_reference/user_id and its email/phone/hash values all land
    in link_keys);
(b) a LINK_RESOURCE_IDENTITY activity visible at audit_at links the
    resource to the person's user_id or email;
(c) it is referenced by an already-linked resource (e.g. a search
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
    from audit.models import Identity, Observation
    from audit.timeview import TimeView
else:
    from .models import Identity, Observation
    from .timeview import TimeView

_LINK_ACTIVITY_RE = re.compile(
    r"(?:linked|confirmed)\s+(\S+)\s*\([^)]*\)\s*(?:to|belongs only to)\s+"
    r"([^\s]+@[^\s]+?)\s+and\s+(user_\d+)"
)

LinkRule = str  # "identity_key", "activity", "reference_closure"


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


def link_observations(
    observations: list[Observation], identity: Identity, time_view: TimeView
) -> list[LinkedObservation]:
    identity_keys = {identity.user_id} | identity.emails | identity.phones | identity.hashes
    activity_links = _activity_links_visible(time_view)

    by_resource: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        if obs.resource_id:
            by_resource[obs.resource_id].append(obs)

    resource_keys: dict[str, set[str]] = {
        rid: set().union(*(o.link_keys for o in obs_list)) for rid, obs_list in by_resource.items()
    }

    rule_by_resource: dict[str, LinkRule] = {}
    for rid, keys in resource_keys.items():
        if keys & identity_keys:
            rule_by_resource[rid] = "identity_key"
            continue
        link = activity_links.get(rid)
        if link and (link[0] in identity_keys or link[1] == identity.user_id):
            rule_by_resource[rid] = "activity"

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
