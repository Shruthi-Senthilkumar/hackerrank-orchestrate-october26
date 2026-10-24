"""Parser for .sql evidence snapshots (F04), via sql_sandbox only.

Handles both real shapes found in Phase 1 profiling:
- "inventory" files (snapshot_scope + 8 typed tables, one captured_at per
  origin_system);
- "two-table" files (a *_primary table and one replica table, either
  typed columns or the generic 5-column record_json layout), with a
  single header "Captured at" time.

Every table actually queried becomes one Coverage record; every row
becomes one Observation with exists=True. Absence is not synthesized
here (this parser cannot know which resource_id a case cares about); a
missing resource in a covered store is inferred later by whoever holds
both the person's known resource ids and this Coverage record.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit import mapping
    from audit.evidence import normalize
    from audit.evidence.sql_sandbox import load_sql_file, SqlSandboxError
    from audit.loaders import EvidenceFile
    from audit.models import Coverage, Observation
else:
    from .. import mapping
    from . import normalize
    from .sql_sandbox import load_sql_file, SqlSandboxError
    from ..loaders import EvidenceFile
    from ..models import Coverage, Observation

# support_platform's two collections disambiguate SUPPORT_MESSAGE vs
# SUPPORT_ATTACHMENT, which mapping.py cannot do from the prefix alone.
COLLECTION_CATEGORY_OVERRIDE = {
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "support_conversations": "SUPPORT_MESSAGE",
}

# inventory-shape table name -> the snapshot_scope origin_system that times it
TABLE_TO_ORIGIN_SYSTEM = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _resolve_system_and_category(resource_id: str, collection_hint: str | None) -> tuple[str, str | None]:
    entry = mapping.mapping_for_resource_id(resource_id) if resource_id else None
    system_id = entry.system_id if entry else "unknown"
    category = entry.data_category if entry else None
    if collection_hint in COLLECTION_CATEGORY_OVERRIDE:
        category = COLLECTION_CATEGORY_OVERRIDE[collection_hint]
    return system_id, category


def _row_to_observation(
    row: dict, store: str, source_id: str, manifest_time: datetime, observed_at: datetime
) -> Observation:
    row = dict(row)
    collection_hint = row.pop("collection_name", None) or store
    if "record_json" in row and row["record_json"]:
        inner = json.loads(row.pop("record_json"))
        row.update(inner)
    resource_id = row.get("resource_id")
    identifiers, link_keys, attrs = normalize.classify_record(row)
    if resource_id:
        link_keys.add(resource_id)
    system_id, category = _resolve_system_and_category(resource_id, collection_hint)
    return Observation(
        system_id=system_id,
        resource_id=resource_id,
        category=category,
        store=store,
        source_id=source_id,
        manifest_time=manifest_time,
        observed_at=observed_at,
        exists=True,
        identifiers_present=frozenset(identifiers),
        attrs=attrs,
        link_keys=frozenset(k for k in link_keys if k),
    )


def parse_sql_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], list[Coverage]]:
    try:
        snap = load_sql_file(resolved_path)
    except SqlSandboxError:
        raise

    observations: list[Observation] = []
    coverage: list[Coverage] = []
    tables = snap.tables()

    try:
        if "snapshot_scope" in tables:
            scope_time_by_origin = {
                origin: _parse_ts(cap)
                for origin, cap in snap.query("SELECT origin_system, captured_at FROM snapshot_scope")
            }
            for table in tables:
                if table == "snapshot_scope":
                    continue
                default_observed_at = scope_time_by_origin.get(
                    TABLE_TO_ORIGIN_SYSTEM.get(table, ""), ev.captured_at
                )
                rows = snap.rows_as_dicts(table)
                for row in rows:
                    sys_id, _ = _resolve_system_and_category(row.get("resource_id"), table)
                    observed_at = scope_time_by_origin.get(sys_id, default_observed_at)
                    observations.append(
                        _row_to_observation(row, table, ev.file_id, ev.captured_at, observed_at)
                    )
                coverage.append(
                    Coverage(store=table, collection=table, observed_at=default_observed_at, source_id=ev.file_id)
                )
        else:
            header_time = snap.header.get("Captured at")
            observed_at = _parse_ts(header_time) if header_time else ev.captured_at
            for table in tables:
                rows = snap.rows_as_dicts(table)
                for row in rows:
                    observations.append(
                        _row_to_observation(row, table, ev.file_id, ev.captured_at, observed_at)
                    )
                coverage.append(
                    Coverage(store=table, collection=table, observed_at=observed_at, source_id=ev.file_id)
                )
    finally:
        snap.close()

    return observations, coverage
