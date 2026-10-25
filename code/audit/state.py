"""F08 support: resource state at audit_at (PRD 7.3).

For a given (system_id, resource_id), determines whether the resource
currently exists, is absent, or is unknown, as of one case's audit_at,
and which evidence id proves it.

Two timelines are combined:
1. Within one snapshot file, primary and replica tables of the same
   logical store are OR'd together first (decision D5 / PRD 7.5
   replication drift: a record present in any replica but absent from
   the primary counts as present for that store).
2. Across files/log events over time, the most RECENT fact (by each
   observation's own observed_at, never by manifest_time -- D15 says
   manifest_time only gates visibility) wins. This is what correctly
   turns an old "present" sighting into "absent" once a later, more
   complete check shows it gone, instead of a stale earlier sighting
   overriding a real deletion.

Absence is only ever established by: an explicit negative observation
(a 404 lookup, rows=0, NOT_FOUND, exists=False), or a Coverage record
for the resource's store that is visible and does not mention the
resource anywhere in that same file. No observation and no covering
Coverage record at all means "unknown", not absent.

Resource_id is globally unique (never shared between people), so
"every Observation of this resource_id in a visible file" is
well-defined regardless of who it ends up linked to; this module takes
the full per-file observation lists (as the registry holds them, not
pre-filtered to one person) and filters by resource_id itself, so
there is exactly one notion of "does this file mention this resource",
used both to read its state and to decide whether a Coverage record
proves absence.
"""

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit import mapping
    from audit.models import Coverage, Observation
else:
    from . import mapping
    from .models import Coverage, Observation

_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)

#: Table-name suffixes that mark a primary/replica variant of the same
#: logical store (profiled in Phase 1: the two-table SQL shape). Used
#: only to OR replica drift together within one snapshot file; never to
#: link a resource to a person (that is link_keys' job).
_REPLICA_SUFFIXES = (
    "_primary",
    "_read_replica",
    "_failover_replica",
    "_reporting_replica",
    "_replica_ap_south",
    "_replica_eu_west",
)


def store_group(store: str) -> str:
    """Collapses a two-table-shape primary/replica pair to one group,
    for replica-drift OR-ing (see module docstring point 1). The
    group name keeps a distinguishing suffix rather than the bare base
    name: the "inventory"-shape family (Phase 1) names its tables with
    the exact same bare words (e.g. "customer_profiles", with no
    suffix at all), and stripping the two-table family's suffix down to
    that same bare word would wrongly collapse two structurally
    unrelated captures into one coverage group -- caught by hand-
    checking case_05 against the PRD's own Appendix C example
    (account_005), where an unrelated, nearly-empty inventory snapshot
    was wrongly "proving" a two-table-family resource absent."""
    for suffix in _REPLICA_SUFFIXES:
        if store.endswith(suffix):
            return store[: -len(suffix)] + "__two_table_family"
    return store


def resource_id_shape(resource_id: str) -> str:
    """A resource_id's "shape" for coverage-trust purposes: its
    mapping.py prefix when it has one (account_, legal_hold_, ...), else
    its own non-digit leading text (e.g. "ORD-" from "ORD-20264402").
    Used only to decide whether a store has EVER indexed this kind of
    id at all -- never to link a resource to a person (D17 forbids
    that; this is purely "could this store even contain this ID
    scheme", not "does this ID belong to this person")."""
    prefix = mapping.prefix_for_resource_id(resource_id)
    if prefix:
        return prefix
    m = re.match(r"^[A-Za-z]+-?", resource_id)
    return m.group(0) if m else resource_id


def build_group_shapes(all_observations_by_file: dict[str, list[Observation]]) -> dict[str, set]:
    """store_group -> every resource_id shape ever observed in it. A
    category match alone is not enough to trust a store's coverage: a
    SQL table that only ever holds legal_hold_NNNN ids was never
    designed to track an ORD-NNNN id from a PDF, even though both
    happen to be LEGAL_HOLD_RECORD category -- caught by hand-checking
    case_21, where an unrelated SQL store's coverage wrongly "proved"
    a real, PDF-sourced legal hold record absent."""
    out: dict[str, set] = {}
    for obs_list in all_observations_by_file.values():
        for o in obs_list:
            out.setdefault(store_group(o.store), set()).add(resource_id_shape(o.resource_id))
    return out


def build_group_categories(all_observations_by_file: dict[str, list[Observation]]) -> dict[str, set]:
    """store_group -> every data_category ever observed in it, across
    the WHOLE registry (not time-filtered -- this is a structural fact
    about which store holds which kind of record, computed once and
    reused for every case). Without this, a coverage record for an
    unrelated store (e.g. an analytics snapshot) could wrongly "prove"
    an account_service resource absent just because that unrelated
    store never mentions it -- a bug caught by hand-checking case_05
    against the PRD's own Appendix C example (account_005)."""
    out: dict[str, set] = {}
    for obs_list in all_observations_by_file.values():
        for o in obs_list:
            if o.category:
                out.setdefault(store_group(o.store), set()).add(o.category)
    return out


@dataclass(frozen=True)
class ResourceState:
    system_id: str
    resource_id: str
    category: Optional[str]
    exists: Optional[bool]  # True, False, or None ("unknown")
    evidence_id: str  # file_id/activity_id proving this state; "" if unknown
    as_of: Optional[datetime]  # the observed_at (or coverage observed_at) that decided this
    attrs: dict  # the attrs of the Observation that decided this state; {} if unknown/coverage-only
    identifiers_present: frozenset  # likewise, from the deciding Observation; frozenset() otherwise


def compute_state(
    system_id: str,
    resource_id: str,
    category: Optional[str],
    all_observations_by_file: dict[str, list[Observation]],
    coverage_records: list[Coverage],
    audit_at: datetime,
    group_categories: Optional[dict[str, set]] = None,
    group_shapes: Optional[dict[str, set]] = None,
    person_linked_resource_ids: Optional[set] = None,
) -> ResourceState:
    """all_observations_by_file: the visible (<=audit_at by manifest
    time, per TimeView) per-file observation lists, exactly as the
    registry holds them -- NOT pre-filtered to any one person, since a
    resource_id is already unique and whether a file mentions it is a
    fact independent of who it is linked to. coverage_records: every
    visible Coverage record. group_categories: the output of
    build_group_categories(), used to restrict coverage-based absence
    to store groups that actually ever hold this resource's category
    (a coverage record for an unrelated store, e.g. an analytics
    snapshot, must never "prove" an account_service resource absent).
    group_shapes: the output of build_group_shapes(), a second,
    finer-grained restriction: even within the same category, a store
    that only ever indexes one id shape (e.g. legal_hold_NNNN) must
    never "prove" a different-shaped id (e.g. a PDF's ORD-NNNN) absent.
    person_linked_resource_ids: every resource_id already linked to
    this same person (across all their categories), required before a
    *scoped* Coverage record (see Coverage.scoped) may prove anything
    absent for them -- a scoped bundle's GROUP only speaks for a person
    if that same group (not just the file as a whole; one file can mix
    a person's own collection with an unrelated, comprehensive one)
    already mentions at least one of their other resources.
    If omitted, coverage-based absence is not applied at all -- callers
    should always pass the real tables in production use."""
    group_categories = group_categories or {}
    group_shapes = group_shapes or {}
    person_linked_resource_ids = person_linked_resource_ids or set()
    # each fact: (exists, evidence_id, as_of, attrs, identifiers_present)
    facts: list[tuple[bool, str, datetime, dict, frozenset]] = []

    # one fact per (file, store_group): OR observations within the group,
    # falling back to coverage-based absence if the group was covered but
    # never mentions this resource.
    groups_by_file: dict[str, set[str]] = {}
    for file_id, obs_list in all_observations_by_file.items():
        for o in obs_list:
            groups_by_file.setdefault(file_id, set()).add(store_group(o.store))
    for c in coverage_records:
        groups_by_file.setdefault(c.source_id, set()).add(store_group(c.store))

    for file_id, groups in groups_by_file.items():
        file_obs = all_observations_by_file.get(file_id, [])
        # A file that produced zero observations across every store it
        # covers is a degenerate/failed capture (grounded signal, not a
        # guess: real inventory snapshots have 20-35 rows; evidence_90
        # has exactly 1 -- its own snapshot_scope row -- and the PRD's
        # own Appendix C example, account_005, shows exactly this file
        # wrongly "proving" an unrelated resource absent if trusted).
        # Its coverage is never used to prove absence, though it can
        # still, correctly, never show anything as present either.
        file_is_degenerate = len(file_obs) == 0
        for group in groups:
            matching = [
                o for o in file_obs if o.resource_id == resource_id and store_group(o.store) == group
            ]
            if any(o.exists for o in matching):
                best = max((o for o in matching if o.exists), key=lambda o: o.observed_at)
                facts.append((True, best.source_id, best.observed_at, best.attrs, best.identifiers_present))
                continue
            if any(o.exists is False for o in matching):
                best = max((o for o in matching if o.exists is False), key=lambda o: o.observed_at)
                facts.append((False, best.source_id, best.observed_at, best.attrs, best.identifiers_present))
                continue
            if category is not None and category not in group_categories.get(group, set()):
                continue  # this store never holds this category; a coverage record here proves nothing
            if resource_id_shape(resource_id) not in group_shapes.get(group, set()):
                continue  # this store never indexes this id shape; its coverage proves nothing either
            if file_is_degenerate:
                continue
            group_coverage = [
                c for c in coverage_records if c.source_id == file_id and store_group(c.store) == group
            ]
            if any(c.scoped for c in group_coverage):
                # Scoped at the GROUP, not the whole file: one bundle file
                # can embed both this person's own per-collection snapshot
                # (e.g. their account_service profile) AND an unrelated,
                # comprehensive sub-collection that just happens to share
                # the file (caught by hand-checking case_473's evidence_45,
                # whose "backup_restore_service"/"operational_record_history"
                # sub-collection lists dozens of OTHER people's account_/
                # search_/support_ ids with zero overlap with case_473's own
                # resources, while the file's OTHER groups are genuinely
                # case_473's own data -- a file-wide check wrongly let that
                # unrelated sub-collection "prove" case_473's own
                # search_service resource absent).
                group_has_other_resource_of_this_person = any(
                    o.resource_id in person_linked_resource_ids
                    for o in file_obs
                    if store_group(o.store) == group
                )
                if not group_has_other_resource_of_this_person:
                    continue  # this group's own slice of a scoped bundle never mentions this person
            if group_coverage:
                cov = max(group_coverage, key=lambda c: c.observed_at)
                facts.append((False, cov.source_id, cov.observed_at, {}, frozenset()))

    facts = [f for f in facts if f[2] <= audit_at]
    if not facts:
        return ResourceState(system_id, resource_id, category, None, "", None, {}, frozenset())

    # Tie-break on source_id too: `groups` above is a set, whose iteration
    # order depends on Python's per-process string hash seed, so two
    # facts with the exact same observed_at (a real possibility -- two
    # different store groups both timestamped at one snapshot's capture
    # time) must not let max() silently prefer whichever happened to be
    # appended first. Adding source_id makes the choice reproducible
    # across runs and interpreters regardless of PYTHONHASHSEED.
    best = max(facts, key=lambda f: (f[2], f[1]))
    return ResourceState(system_id, resource_id, category, best[0], best[1], best[2], best[3], best[4])
