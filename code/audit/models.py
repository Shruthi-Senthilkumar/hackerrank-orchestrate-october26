"""Core data model for identity, evidence observations, and coverage.

PRD section 5.2, refined by the Phase 2 kickoff's more specific field
list. `ResourceState` and `Finding` are not needed until Phase 3 (policy
and planning) and are intentionally not built yet.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class Identity:
    """A person's identifiers, reconstructed as of one case's audit_at."""

    user_id: str
    current_name: str
    current_email: str
    current_phone: str
    current_email_hash: str
    emails: frozenset[str]
    phones: frozenset[str]
    hashes: frozenset[str]


@dataclass(frozen=True)
class Observation:
    """One normalized fact read from one evidence file or activity/audit row.

    `manifest_time` is the evidence file's own manifest captured_at (or the
    activity/audit row's event_time); per D15 this is what gates VISIBILITY
    and CITATION (TimeView.visible_evidence_files already enforces this
    upstream of every parser). `observed_at` is the inner timestamp used
    only to decide RECENCY among already-visible observations of the same
    resource (e.g. a JSON bundle's per-snapshot captured_at); it is never
    used to decide visibility.
    """

    system_id: str
    resource_id: str
    category: Optional[str]
    store: str
    source_id: str
    manifest_time: datetime
    observed_at: datetime
    exists: Optional[bool]
    identifiers_present: frozenset[str] = field(default_factory=frozenset)
    attrs: dict[str, Any] = field(default_factory=dict)
    link_keys: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TraceHint:
    """One identifier value seen on a log line that shares a `trace_id`
    with other lines in the same file, but carries no resource_id of its
    own (e.g. a "profile_lookup_started" line with a lookup_key but not
    yet a resolved resource). Used only by code/audit/linker.py's
    trace_correlation rule: if a hint's value matches a person's
    identity, every OTHER (resource-bearing) line of the same trace_id,
    visible at that case's audit_at, belongs to that person too.

    `event_time` is this specific line's own timestamp, kept (not
    collapsed into the file's single manifest_time) so the
    trace_correlation rule can ignore a hint whose own line falls after
    a case's audit_at even though its file is otherwise visible.
    """

    trace_id: str
    value: str
    event_time: datetime
    source_id: str


@dataclass(frozen=True)
class DocumentHint:
    """One identifier value found anywhere in a free-text document
    (currently: the 2 PDFs with no regular row structure). Used only by
    code/audit/linker.py's same_document rule: a document that contains
    both a known resource-id shape and an identifier of the person
    links every resource_id found in that same document to them. Mirrors
    TraceHint's shape; kept as a separate type since "a trace" and "a
    document" are different, non-interchangeable groupings even though
    the matching mechanism (code/audit/linker.py's
    _group_values_matching_identity) is shared.
    """

    document_id: str
    value: str
    event_time: datetime
    source_id: str


@dataclass(frozen=True)
class Coverage:
    """Proof that a store/collection was actually inspected.

    An empty result set for a covered store/collection is evidence of
    absence; the absence of a Coverage record means the question was
    simply never asked by any visible evidence, which is "unknown", not
    "absent".

    `scoped`: True only for a JSON "snapshot bundle" (the
    `customer_data_snapshot_bundle_*.json` family). Hand-checking
    case_21 vs. case_31 (both linked to the same evidence_51 bundle,
    which is case_31's own personalized evidence package -- its other
    collections name only case_31's resources) showed a bundle is a
    scoped, per-case evidence package, not a comprehensive platform
    dump the way the SQL inventory/two-table files genuinely are
    (dozens of unrelated people's rows in one file). A scoped
    Coverage record may only prove absence for a person who already
    has at least one OTHER resource observed in that same file;
    everyone else's absence from it is simply not evidence about them.
    """

    store: str
    collection: str
    observed_at: datetime
    source_id: str
    scoped: bool = False
