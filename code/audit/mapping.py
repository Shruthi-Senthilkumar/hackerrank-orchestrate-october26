"""Resource-id-prefix -> system_id -> data_category mapping.

F (supports F06/F08). Built from PRD section 3.4 plus what Phase 1
profiling actually proved by reading the global activity stream and every
evidence file (see code/evaluation/profile_report.md for the evidence).
Unproven prefixes are deliberately left out here; they are listed as
Unresolved in the profile report instead of being guessed.

Two categories could not be grounded in any prefix, system_id, or evidence
record anywhere in the dataset: SECONDARY_IDENTIFIER (rule_02) and
PRODUCT_TELEMETRY (rule_08). The only "telemetry" text found
(evidence/logs/cloud_runtime_export_*.log, event=telemetry_flushed) is
generic cloud-infrastructure telemetry with no resource_id or customer
link, not a customer PRODUCT_TELEMETRY record. Do not map either category
until confirmed by the user.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryMapping:
    prefix: str
    system_id: str
    data_category: str
    note: str = ""


MAPPINGS: list[CategoryMapping] = [
    CategoryMapping("account_", "account_service", "USER_PROFILE"),
    CategoryMapping("search_", "search_service", "SEARCH_INDEX_ENTRY"),
    CategoryMapping(
        "support_",
        "support_platform",
        "SUPPORT_MESSAGE",
        "or SUPPORT_ATTACHMENT when the record's collection/context is "
        "ticket_attachments rather than support_conversations; decide from content.",
    ),
    CategoryMapping("analytics_", "analytics_platform", "ANALYTICS_PROFILE"),
    CategoryMapping("audit_record_", "security_service", "SECURITY_AUDIT_LOG"),
    CategoryMapping("data_flow_", "integration_service", "ACTIVE_DATA_FLOW"),
    CategoryMapping("backup_", "backup_service", "BACKUP_ARCHIVE"),
    CategoryMapping("export_", "export_service", "USER_EXPORT"),
    CategoryMapping("tombstone_", "identity_service", "ACCOUNT_TOMBSTONE"),
    CategoryMapping(
        "legal_hold_",
        "legal_service",
        "LEGAL_HOLD_RECORD",
        "confirmed via the activity stream (legal_service target) and the "
        "retained_order_records collection in the generic record_json SQL tables.",
    ),
    CategoryMapping(
        "email_delivery_",
        "email_delivery_service",
        "EMAIL_DELIVERY_LOG",
        "prefix/system confirmed only via the activity stream (email_delivery_service / "
        "notification_service); no evidence file contains an email_delivery_NNNN resource_id. "
        "(Correction: an earlier version of this note wrongly cited the notification_delivery "
        "log family, which is account_service USER_PROFILE lookups, not email-delivery records. "
        "See DECISIONS.md D16; re-checked once images are read in Phase 4.)",
    ),
    CategoryMapping(
        "cache_",
        "cache_service",
        "CACHE_ENTRY",
        "confirmed only via REFRESH_CACHE rows in the activity stream (account_service -> "
        "cache_service); no evidence file ever materializes a concrete cache_NNNN record.",
    ),
    CategoryMapping(
        "marketing_",
        "marketing_platform",
        "MARKETING_PROFILE",
        "confirmed via a LINK_RESOURCE_IDENTITY activity row and "
        "evidence/images/marketing_profile_console.png.",
    ),
    CategoryMapping(
        "object_",
        "object_storage",
        "SUPPORT_ATTACHMENT",
        "raw object-storage file (e.g. a PDF), distinct from support_platform's own "
        "ticket_attachments collection; confirmed via a LINK_RESOURCE_IDENTITY "
        "activity row and evidence/images/object_storage_browser_*.png.",
    ),
]

UNRESOLVED_CATEGORIES = ["SECONDARY_IDENTIFIER", "PRODUCT_TELEMETRY"]


def prefix_for_resource_id(resource_id: str) -> str | None:
    for mapping in sorted(MAPPINGS, key=lambda m: -len(m.prefix)):
        if resource_id.startswith(mapping.prefix):
            return mapping.prefix
    return None


def mapping_for_resource_id(resource_id: str) -> CategoryMapping | None:
    prefix = prefix_for_resource_id(resource_id)
    if prefix is None:
        return None
    return next(m for m in MAPPINGS if m.prefix == prefix)


#: Matches any known prefix followed by digits, e.g. "account_001",
#: "support_4218". Used to find resource-id-shaped tokens in free text
#: (PDF/image documents), never to invent a new prefix.
RESOURCE_ID_RE = re.compile(
    "(" + "|".join(re.escape(m.prefix) for m in sorted(MAPPINGS, key=lambda m: -len(m.prefix))) + r")(\d+)\b"
)


def find_resource_ids_in_text(text: str) -> list[str]:
    return [f"{prefix}{digits}" for prefix, digits in RESOURCE_ID_RE.findall(text)]


def disambiguate_support_category(
    context_text: str, default: str = "SUPPORT_MESSAGE", service: str = ""
) -> str:
    """support_ is ambiguous between SUPPORT_MESSAGE and SUPPORT_ATTACHMENT
    (see the support_ mapping's note). Grounded in the real vocabulary
    profiled across the 26 logs (attachment_pii_scan/attachment_scan_
    started/thumbnail_failed vs. message_pii_scan/message_scan_started)
    and reused here for PDF/document context text, which uses the same
    words in plain English ("attachment", "thumbnail") vs. ("message").

    A second, independent grounded signal: the `support_replica` log
    family's own event vocabulary (contact_query_started/_completed,
    deletion_marker_check, batch_started, checkpoint_saved) never uses
    either keyword at all -- checked across its full event list -- so
    when neither keyword matches, the originating service name is used
    as a tiebreaker. support_replica never mentions message content,
    only contact/attachment-style metadata checks, so it defaults to
    SUPPORT_ATTACHMENT instead of the generic default.
    """
    lowered = context_text.lower()
    if "attachment" in lowered or "thumbnail" in lowered:
        return "SUPPORT_ATTACHMENT"
    if "message" in lowered:
        return "SUPPORT_MESSAGE"
    if service == "support_replica":
        return "SUPPORT_ATTACHMENT"
    return default
