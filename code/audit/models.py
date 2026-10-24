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
class Coverage:
    """Proof that a store/collection was actually inspected.

    An empty result set for a covered store/collection is evidence of
    absence; the absence of a Coverage record means the question was
    simply never asked by any visible evidence, which is "unknown", not
    "absent".
    """

    store: str
    collection: str
    observed_at: datetime
    source_id: str
