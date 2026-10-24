"""The single gateway for every time-dependent read.

F02. No module outside this file (and code/audit/loaders.py, which only
type-converts rows and does no filtering) may read the raw global
activity stream, the identity audit log, or the evidence manifest, or
decide whether a timestamp found inside an evidence file is visible. All
of that goes through a `TimeView(audit_at)` instance.

Visibility rule: a row/timestamp is visible to a case with cutoff
`audit_at` iff its own timestamp is <= audit_at (inclusive boundary).
Evidence or activity captured strictly after audit_at must never be
returned, cited, or used to decide anything for that case.
"""

from datetime import datetime

from . import loaders


class TimeView:
    """Time-travel view of all time-dependent tables, cut off at `audit_at`."""

    def __init__(self, audit_at: datetime):
        self.audit_at = audit_at
        self._all_activity = loaders.load_system_activity()
        self._all_audit_log = loaders.load_user_audit_log()
        self._all_evidence_files = loaders.load_evidence_files()

    def is_visible(self, timestamp: datetime) -> bool:
        """True iff `timestamp` is at or before this view's audit_at."""
        return timestamp <= self.audit_at

    def visible_activity(self) -> list[loaders.ActivityEntry]:
        return [a for a in self._all_activity if self.is_visible(a.event_time)]

    def visible_audit_log(self) -> list[loaders.AuditLogEntry]:
        return [a for a in self._all_audit_log if self.is_visible(a.event_time)]

    def visible_evidence_files(self) -> list[loaders.EvidenceFile]:
        return [e for e in self._all_evidence_files if self.is_visible(e.captured_at)]


def build_time_view(audit_at: datetime) -> TimeView:
    return TimeView(audit_at)


def all_audit_log_entries() -> list[loaders.AuditLogEntry]:
    """The complete, unfiltered identity audit log.

    The one sanctioned escape hatch from per-case `<= audit_at`
    visibility: code/audit/identity.py's as-of-any-timestamp
    reconstruction must legitimately see entries on both sides of its
    reference time (to "undo" a change that happened after it and
    recover the value held before it), and must find every user who
    ever held a given email across all history before bounding that
    user's identity set to one case's audit_at. That still goes through
    this module -- the one place allowed to call
    loaders.load_user_audit_log() -- rather than reading it directly.
    """
    return loaders.load_user_audit_log()
