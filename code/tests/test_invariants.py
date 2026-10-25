"""Phase 3b task 1e: a global, dataset-wide invariant over all 518 real
cases. A resource linked to two different user_ids must be linked to
EACH of them only through identity_key or same_document -- never
through reference_closure (the rule most prone to bridging through a
value that is not really this person's own identity). Run once per
test session; printed numbers double as the sanity-run report line.
"""

import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import loaders, identity  # noqa: E402
from audit.evidence.registry import (  # noqa: E402
    build_registry,
    visible_document_hints,
    visible_observations,
    visible_trace_hints,
)
from audit.linker import link_observations  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402


def test_no_resource_is_cross_person_linked_via_reference_closure():
    reg = build_registry()
    requests = loaders.load_deletion_requests()

    # rid -> {(user_id, rule)}
    resource_links: dict[str, set] = defaultdict(set)

    for req in requests:
        resolution = identity.resolve_request_email(req.email, req.requested_at)
        if resolution.user_id is None:
            continue
        tv = build_time_view(req.audit_at)
        ident = identity.build_identity(resolution.user_id, req.audit_at)
        obs = visible_observations(reg, tv)
        trace_hints = visible_trace_hints(reg, tv)
        doc_hints = visible_document_hints(reg, tv)
        linked = link_observations(obs, ident, tv, trace_hints, doc_hints)

        by_resource: dict[str, list] = defaultdict(list)
        for l in linked:
            by_resource[l.observation.resource_id].append(l)
        for rid, entries in by_resource.items():
            resource_links[rid].add((resolution.user_id, entries[0].rule))

    violations = []
    for rid, links in resource_links.items():
        users = {u for u, _ in links}
        if len(users) < 2:
            continue
        rules = {r for _, r in links}
        if "reference_closure" in rules:
            violations.append((rid, users, rules))

    for rid, users, rules in violations:
        print(f"INVARIANT VIOLATION: {rid} linked to {len(users)} users via {rules}")

    assert violations == [], f"{len(violations)} resource(s) cross-person-linked via reference_closure"
