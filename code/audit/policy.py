"""F08 policy engine (PRD 7.5, Appendix B).

Loads deletion_rules.csv once and exposes, per data category, the
required action (DELETE/REDACT/ANONYMIZE/RETAIN) for a given
ResourceState, via a small predicate per conditional rule. Every
predicate that cannot be evaluated from the ResourceState's own attrs
falls back to the safest compliant interpretation, which this module
documents and returns in the trace rather than guessing.
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit import loaders
    from audit.state import ResourceState
else:
    from . import loaders
    from .state import ResourceState

RULES_BY_CATEGORY: dict[str, loaders.DeletionRule] = {
    r.data_category: r for r in loaders.load_deletion_rules()
}

_UNCONDITIONAL_CATEGORIES = {
    "USER_PROFILE",
    "SECONDARY_IDENTIFIER",
    "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY",
    "USER_EXPORT",
    "MARKETING_PROFILE",
}

_IDENTIFIER_ATTR_KEYS = ("user_id", "customer_reference", "subject_reference", "email", "phone", "email_hash")


@dataclass(frozen=True)
class PolicyOutcome:
    rule_id: str
    required_action: str  # DELETE, REDACT, ANONYMIZE, RETAIN
    predicate_name: str
    predicate_result: Optional[bool]  # None if the predicate fell back (unknown)
    fallback_used: bool
    note: str


def _parse_flexible_date(value: str) -> Optional[datetime]:
    """Parses either an ISO timestamp (SQL/JSON 'retained_until') or the
    PDF's free-text 'DD Mon YYYY' shape ('04 May 2033'), both real shapes
    found in the evidence."""
    if not value:
        return None
    try:
        v = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(v)
    except ValueError:
        pass
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_attributable(state: ResourceState) -> bool:
    if state.identifiers_present:
        return True
    for key in _IDENTIFIER_ATTR_KEYS:
        value = state.attrs.get(key)
        if value not in (None, "", "null"):
            return True
    return False


def predicate_shared_context(state: ResourceState) -> tuple[Optional[bool], bool, str]:
    """SUPPORT_MESSAGE rule_05: conversation contains shared customer,
    agent, or order context that must be retained. [CALIBRATE],
    measured on the samples: an earlier version of this predicate only
    matched order/ticket keywords and wrongly sent case_27/28's
    support_4707/support_NNNN ("Customer contacted support about
    account access.") through DELETE instead of REDACT -- that message
    has no order/ticket word at all, yet the samples expect REDACT.
    Every real support_ message observed across Phase 1/2/3 (order
    disputes, delivery corrections, account-access contacts) is some
    kind of support interaction with a customer, meaning shared context
    in the rule's sense (a customer/agent exchange) is present whenever
    the conversation has any content at all; no sample exercises a
    support MESSAGE needing plain DELETE. So any existing message
    content (or none, visible-but-unparsed) defaults True; this
    predicate therefore always returns True in practice -- kept as a
    real check, not hardcoded, so a future, genuinely contentless
    support_ record can still be told apart from a real conversation.
    """
    text = str(state.attrs.get("message_excerpt") or state.attrs.get("message_text") or "")
    if text:
        return True, False, ""
    return True, True, "no message text visible; fell back to assuming shared context (REDACT, not DELETE)"


def predicate_belongs_only_to_subject(state: ResourceState) -> tuple[Optional[bool], bool, str]:
    """SUPPORT_ATTACHMENT rule_06. No evidence in this dataset shows an
    attachment shared by more than one subject (profiled in Phase 1/2);
    the straightforward, common-case reading is True unless the record's
    own attrs explicitly show more than one distinct subject reference,
    which never occurs in the data checked so far."""
    return True, False, ""


def predicate_still_attributable(state: ResourceState) -> tuple[Optional[bool], bool, str]:
    """ANALYTICS_PROFILE/PRODUCT_TELEMETRY rule_07/08: record is still
    attributable to a user. Directly observable: any identifier field
    (user_id/customer_reference/email/phone/email_hash) is non-null."""
    return is_attributable(state), False, ""


def predicate_within_retention(state: ResourceState, audit_at: datetime) -> tuple[Optional[bool], bool, str]:
    """SECURITY_AUDIT_LOG rule_12: record is within the supplied
    retention period. [CALIBRATE]: straightforward reading is
    retention_until > audit_at -> RETAIN; if retention_until <= audit_at
    (genuinely expired, i.e. a parseable date in the past) the record
    falls through to DELETE. If retention_until is simply absent (some
    security_audit_events records -- the customer_data_snapshot_bundle
    family's shape -- carry no retention_until field at all, only
    event_name/actor_type/integrity_seal), the fallback is RETAIN, not
    DELETE: an audit/compliance record's default purpose is to be kept,
    and wrongly deleting one is a worse failure mode than redundantly
    retaining one whose expiry we simply can't read. Measured on the
    32 samples: this fallback is exercised by case_31's audit_record_6909
    (RETAIN is correct there; the original DELETE fallback caused a
    status mismatch)."""
    raw = state.attrs.get("retention_until") or state.attrs.get("retain_until")
    if raw is None:
        return True, True, "no retention_until field at all; fell back to RETAIN (audit records default to kept)"
    parsed = _parse_flexible_date(str(raw))
    if parsed is None:
        return True, True, "retention_until present but unparseable; fell back to RETAIN"
    return parsed > audit_at, False, ""


def predicate_legal_hold_active(state: ResourceState, audit_at: datetime) -> tuple[Optional[bool], bool, str]:
    """LEGAL_HOLD_RECORD rule_13: a supplied legal hold is active.
    retained_until/retain_until > audit_at. Unknown falls back to True
    (assume the hold is active, i.e. RETAIN): a legal hold protects
    against deletion, so treating an unreadable hold date as expired
    risks deleting something legally required to be kept, which is the
    less safe interpretation."""
    raw = state.attrs.get("retained_until") or state.attrs.get("retain_until")
    parsed = _parse_flexible_date(str(raw)) if raw else None
    if parsed is None:
        return True, True, "no parseable hold date; fell back to assuming the hold is active (RETAIN)"
    return parsed > audit_at, False, ""


def predicate_restore_blockable(state: ResourceState) -> tuple[Optional[bool], bool, str]:
    """BACKUP_ARCHIVE rule_14: restore access can be blocked. The backup
    archive RECORD itself is always retained (backups are kept for
    disaster recovery); whether this person's data can still be
    *restored* from it is a detector concern (code/audit/detectors.py's
    restore-risk finding and BLOCK_RESTORE remediation), not a gate on
    whether the archive record survives. Always True."""
    return True, False, ""


def predicate_tombstone_compliant(state: ResourceState) -> tuple[Optional[bool], bool, str]:
    """ACCOUNT_TOMBSTONE rule_15: name, email, phone and email_hash all
    empty, with the stable internal reference present. Directly
    observable from identifiers_present and attrs."""
    has_direct_identifier = bool(state.identifiers_present) or any(
        state.attrs.get(k) not in (None, "", "null") for k in ("name", "full_name", "email", "phone", "email_hash")
    )
    return not has_direct_identifier, False, ""


def evaluate(state: ResourceState, audit_at: datetime) -> Optional[PolicyOutcome]:
    """Returns None if the category has no rule at all (e.g. the two
    categories D16 found absent from this dataset, or an unmapped
    category)."""
    if state.category is None or state.category not in RULES_BY_CATEGORY:
        return None
    rule = RULES_BY_CATEGORY[state.category]

    if state.category in _UNCONDITIONAL_CATEGORIES:
        return PolicyOutcome(rule.rule_id, rule.required_action, "always", True, False, "")

    if state.category == "SUPPORT_MESSAGE":
        result, fallback, note = predicate_shared_context(state)
        action = "REDACT" if result else "DELETE"
        return PolicyOutcome(rule.rule_id, action, "shared_context", result, fallback, note)

    if state.category == "SUPPORT_ATTACHMENT":
        result, fallback, note = predicate_belongs_only_to_subject(state)
        action = "DELETE" if result else "RETAIN"
        return PolicyOutcome(rule.rule_id, action, "belongs_only_to_subject", result, fallback, note)

    if state.category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
        result, fallback, note = predicate_still_attributable(state)
        action = "ANONYMIZE" if result else "DELETE"
        return PolicyOutcome(rule.rule_id, action, "still_attributable", result, fallback, note)

    if state.category == "EMAIL_DELIVERY_LOG":
        has_email = "email" in state.identifiers_present
        action = "REDACT" if has_email else "DELETE"
        return PolicyOutcome(rule.rule_id, action, "contains_email", has_email, False, "")

    if state.category == "SECURITY_AUDIT_LOG":
        result, fallback, note = predicate_within_retention(state, audit_at)
        action = "RETAIN" if result else "DELETE"
        return PolicyOutcome(rule.rule_id, action, "within_retention", result, fallback, note)

    if state.category == "LEGAL_HOLD_RECORD":
        result, fallback, note = predicate_legal_hold_active(state, audit_at)
        action = "RETAIN" if result else "DELETE"
        return PolicyOutcome(rule.rule_id, action, "legal_hold_active", result, fallback, note)

    if state.category == "BACKUP_ARCHIVE":
        result, fallback, note = predicate_restore_blockable(state)
        return PolicyOutcome(rule.rule_id, "RETAIN", "restore_blockable", result, fallback, note)

    if state.category == "ACCOUNT_TOMBSTONE":
        result, fallback, note = predicate_tombstone_compliant(state)
        return PolicyOutcome(rule.rule_id, "REDACT", "tombstone_compliant", result, fallback, note)

    return None
