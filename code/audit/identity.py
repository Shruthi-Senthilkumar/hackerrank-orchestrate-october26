"""F03 identity resolver (PRD 7.1).

Builds, per user, an as-of-audit_at reconstruction of email/phone/
email_hash from the current snapshot (user_identities.csv, via
code/audit/loaders.py) plus the historical identity-change log (via
code/audit/timeview.py's all_audit_log_entries(), never read directly;
see that function's docstring for why this module needs the full,
unfiltered log rather than one case's visible subset). Resolves a
request email to a user_id through both current and historical values.
Names are a weak signal only and never resolve identity by themselves.
"""

import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit import loaders, timeview
    from audit.models import Identity
else:
    from . import loaders, timeview
    from .models import Identity

TRACKED_FIELDS = ("email", "email_hash", "phone")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def sha256_email(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _FieldEvent:
    event_time: datetime
    old_value: str
    new_value: str


@lru_cache(maxsize=1)
def _events_by_user_field() -> dict[tuple[str, str], list[_FieldEvent]]:
    by_user_field: dict[tuple[str, str], list[_FieldEvent]] = defaultdict(list)
    for entry in timeview.all_audit_log_entries():
        if entry.field_name not in TRACKED_FIELDS:
            continue
        by_user_field[(entry.user_id, entry.field_name)].append(
            _FieldEvent(entry.event_time, entry.old_value, entry.new_value)
        )
    for key, events in by_user_field.items():
        events.sort(key=lambda e: e.event_time)
    return by_user_field


@lru_cache(maxsize=1)
def _identities_by_user_id() -> dict[str, loaders.Identity]:
    return {ident.user_id: ident for ident in loaders.load_user_identities()}


def _snapshot_value(user_id: str, field: str) -> str:
    ident = _identities_by_user_id()[user_id]
    return {"email": ident.email, "email_hash": ident.email_hash, "phone": ident.phone}[field]


def _as_of_value_and_held_set(user_id: str, field: str, audit_at: datetime) -> tuple[str, set[str]]:
    """Return (value held exactly at audit_at, every value held at any time <= audit_at)."""
    events = _events_by_user_field().get((user_id, field), [])
    held: set[str] = set()

    events_at_or_before = [e for e in events if e.event_time <= audit_at]
    events_after = [e for e in events if e.event_time > audit_at]

    for e in events_at_or_before:
        held.add(e.old_value)
        held.add(e.new_value)

    if events_at_or_before:
        as_of_value = events_at_or_before[-1].new_value
    elif events_after:
        # Nothing changed by audit_at; the value has been the pre-change
        # value (the earliest future event's old_value) since account
        # creation, which is therefore also held at every time <= audit_at.
        as_of_value = events_after[0].old_value
        held.add(as_of_value)
    else:
        as_of_value = _snapshot_value(user_id, field)
        held.add(as_of_value)

    held.discard("")
    return as_of_value, held


def build_identity(user_id: str, audit_at: datetime) -> Identity:
    current_email, emails = _as_of_value_and_held_set(user_id, "email", audit_at)
    current_phone, phones = _as_of_value_and_held_set(user_id, "phone", audit_at)
    current_hash, hashes = _as_of_value_and_held_set(user_id, "email_hash", audit_at)

    emails = {normalize_email(e) for e in emails if e}
    current_email = normalize_email(current_email) if current_email else ""
    hashes = {h.strip().lower() for h in hashes if h}
    current_hash = current_hash.strip().lower() if current_hash else ""
    hashes |= {sha256_email(e) for e in emails}

    ident = _identities_by_user_id()[user_id]
    return Identity(
        user_id=user_id,
        current_name=ident.name,
        current_email=current_email,
        current_phone=current_phone,
        current_email_hash=current_hash,
        emails=frozenset(emails),
        phones=frozenset(p for p in phones if p),
        hashes=frozenset(hashes),
    )


@lru_cache(maxsize=1)
def _email_to_user_ids() -> dict[str, frozenset[str]]:
    """Every email -> every user_id who ever held it, at any point in the
    full history (current snapshot or any audit-log value), regardless of
    any particular case's audit_at. Used only to find resolution
    candidates; the per-case Identity is still built bounded by audit_at."""
    index: dict[str, set[str]] = defaultdict(set)
    for ident in loaders.load_user_identities():
        if ident.email:
            index[normalize_email(ident.email)].add(ident.user_id)
    for entry in timeview.all_audit_log_entries():
        if entry.field_name != "email":
            continue
        if entry.old_value:
            index[normalize_email(entry.old_value)].add(entry.user_id)
        if entry.new_value:
            index[normalize_email(entry.new_value)].add(entry.user_id)
    return {email: frozenset(users) for email, users in index.items()}


@dataclass(frozen=True)
class ResolutionResult:
    user_id: str | None
    is_historical: bool  # True if the email is not the current snapshot email
    is_ambiguous: bool
    candidates: tuple[str, ...]


def resolve_request_email(email: str, requested_at: datetime) -> ResolutionResult:
    email = normalize_email(email)
    candidates = _email_to_user_ids().get(email, frozenset())

    if not candidates:
        return ResolutionResult(user_id=None, is_historical=False, is_ambiguous=False, candidates=())

    candidates = tuple(sorted(candidates))
    is_current = any(_identities_by_user_id()[uid].email == email for uid in candidates)

    if len(candidates) == 1:
        return ResolutionResult(
            user_id=candidates[0], is_historical=not is_current, is_ambiguous=False, candidates=candidates
        )

    # Ambiguous: prefer the user whose timeline held this email at requested_at.
    holders_at_requested_at = [
        uid for uid in candidates if email in _as_of_value_and_held_set(uid, "email", requested_at)[1]
    ]
    chosen = holders_at_requested_at[0] if len(holders_at_requested_at) == 1 else candidates[0]
    return ResolutionResult(user_id=chosen, is_historical=not is_current, is_ambiguous=True, candidates=candidates)


def report_identity_statistics(requests: list[loaders.DeletionRequest]) -> dict:
    resolved = 0
    current = 0
    historical = 0
    ambiguous = 0
    unresolved = []
    for req in requests:
        result = resolve_request_email(req.email, req.requested_at)
        if result.user_id is None:
            unresolved.append(req.case_id)
            continue
        resolved += 1
        if result.is_historical:
            historical += 1
        else:
            current += 1
        if result.is_ambiguous:
            ambiguous += 1
    return {
        "total": len(requests),
        "resolved": resolved,
        "current": current,
        "historical": historical,
        "ambiguous": ambiguous,
        "unresolved_case_ids": unresolved,
    }


if __name__ == "__main__":
    all_requests = loaders.load_deletion_requests() + loaders.load_sample_deletion_requests()
    stats = report_identity_statistics(all_requests)
    for k, v in stats.items():
        if k == "unresolved_case_ids":
            print(f"{k}: {v}")
        else:
            print(f"{k}: {v}")
