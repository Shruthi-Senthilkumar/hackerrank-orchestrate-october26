"""Parser for the JSON (and one plain-text) evidence records (F04).

Six JSON shapes found in Phase 1 profiling, dispatched by top-level keys:
- bundles (`exported_at`, `snapshots[]`, each with its own `captured_at`,
  `data_store`, `collection`, `records[]`); an empty `records[]` is
  coverage proving absence for that snapshot;
- a single-collection dump (`captured_at`, `collection`, `records[]`):
  customer_analytics_report, customer_export_jobs;
- a flat lookup-result list (`exported_at`, `records[]`, each
  `record_type` + `result` FOUND/NOT_FOUND): connector_configurations,
  customer_export_manifest, security_audit_ledger;
- a nested per-service export (`exported_at`, `service_exports{service:
  {collection: [...]}}`): service_resource_export.

Per D15, `manifest_time` on every Observation is the file's own
evidence-manifest captured_at (gates visibility, enforced upstream by
TimeView before this parser is ever called); any per-snapshot or
per-record inner timestamp becomes `observed_at` (recency only).
"""

import json
import re as _re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit import mapping
    from audit.evidence import normalize
    from audit.loaders import EvidenceFile
    from audit.models import Coverage, Observation
else:
    from .. import mapping
    from . import normalize
    from ..loaders import EvidenceFile
    from ..models import Coverage, Observation

def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _expand_resource_records(obj) -> list[dict]:
    """Recursively collect every dict carrying its own resource_id,
    including ones nested inside another record's fields (e.g. a
    search_service index_queries record's `hits.documents[]`)."""
    found: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "resource_id" in o and o["resource_id"]:
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(obj)
    return found


def _record_to_observation(
    record: dict, store: str, source_id: str, manifest_time: datetime, observed_at: datetime
) -> Observation:
    record = dict(record)
    resource_id = record.get("resource_id")
    result = record.pop("result", None)
    record_type = record.pop("record_type", None)
    exists = True
    if result in ("FOUND", "NOT_FOUND"):
        exists = result == "FOUND"

    identifiers, link_keys, attrs, references = normalize.classify_record(record)
    if resource_id:
        link_keys.add(resource_id)
    if result is not None:
        attrs["result"] = result

    entry = mapping.mapping_for_resource_id(resource_id) if resource_id else None
    system_id = entry.system_id if entry else "unknown"
    category = record_type if record_type else (entry.data_category if entry else None)

    return Observation(
        system_id=system_id,
        resource_id=resource_id,
        category=category,
        store=store,
        source_id=source_id,
        manifest_time=manifest_time,
        observed_at=observed_at,
        exists=exists,
        identifiers_present=frozenset(identifiers),
        attrs=attrs,
        link_keys=frozenset(k for k in link_keys if k),
        references=frozenset(r for r in references if r and r != resource_id),
    )


def _parse_bundle(data: dict, ev: EvidenceFile) -> tuple[list[Observation], list[Coverage]]:
    observations: list[Observation] = []
    coverage: list[Coverage] = []
    for snap in data.get("snapshots", []):
        store = snap.get("data_store") or snap.get("collection")
        collection = snap.get("collection")
        observed_at = _parse_ts(snap["captured_at"]) if snap.get("captured_at") else ev.captured_at
        records = snap.get("records", [])
        for rec in _expand_resource_records(records):
            observations.append(_record_to_observation(rec, store, ev.file_id, ev.captured_at, observed_at))
        coverage.append(
            Coverage(store=store, collection=collection, observed_at=observed_at, source_id=ev.file_id, scoped=True)
        )
    return observations, coverage


def _parse_single_collection(data: dict, ev: EvidenceFile) -> tuple[list[Observation], list[Coverage]]:
    store = data.get("collection")
    observed_at = _parse_ts(data["captured_at"]) if data.get("captured_at") else ev.captured_at
    records = data.get("records", [])
    observations = [
        _record_to_observation(rec, store, ev.file_id, ev.captured_at, observed_at)
        for rec in _expand_resource_records(records)
    ]
    coverage = [Coverage(store=store, collection=store, observed_at=observed_at, source_id=ev.file_id)]
    return observations, coverage


def _parse_flat_lookup_list(data: dict, ev: EvidenceFile, family_name: str) -> tuple[list[Observation], list[Coverage]]:
    observed_at = _parse_ts(data["exported_at"]) if data.get("exported_at") else ev.captured_at
    records = data.get("records", [])
    observations = [
        _record_to_observation(rec, family_name, ev.file_id, ev.captured_at, observed_at)
        for rec in _expand_resource_records(records)
    ]
    coverage = [Coverage(store=family_name, collection=family_name, observed_at=observed_at, source_id=ev.file_id)]
    return observations, coverage


def _parse_service_resource_export(data: dict, ev: EvidenceFile) -> tuple[list[Observation], list[Coverage]]:
    observations: list[Observation] = []
    coverage: list[Coverage] = []
    file_observed_at = _parse_ts(data["exported_at"]) if data.get("exported_at") else ev.captured_at
    for service, collections in data.get("service_exports", {}).items():
        for collection, items in collections.items():
            store = f"{service}.{collection}"
            for rec in _expand_resource_records(items):
                rec_observed_at = (
                    _parse_ts(rec["observed_at"]) if rec.get("observed_at") else file_observed_at
                )
                observations.append(
                    _record_to_observation(rec, store, ev.file_id, ev.captured_at, rec_observed_at)
                )
            coverage.append(
                Coverage(store=store, collection=collection, observed_at=file_observed_at, source_id=ev.file_id)
            )
    return observations, coverage


def parse_json_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], list[Coverage]]:
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"unexpected top-level JSON shape (not an object) in {ev.file_path}")

    if "snapshots" in data:
        return _parse_bundle(data, ev)
    if "service_exports" in data:
        return _parse_service_resource_export(data, ev)
    if "collection" in data and "records" in data:
        return _parse_single_collection(data, ev)
    if "records" in data:
        family_name = _re.sub(r"_\d{8}(_\d+)?$", "", Path(ev.file_path).stem)
        return _parse_flat_lookup_list(data, ev, family_name)

    raise ValueError(f"unrecognized JSON evidence shape in {ev.file_path}: keys={sorted(data.keys())}")
