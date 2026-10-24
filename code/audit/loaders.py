"""Explicit UTF-8 loaders for the eight participant-facing CSV files.

F01. Every loader here reads the raw table with no time filtering and no
evidence-content parsing; it only type-converts columns. Phase 1 scope:
these are the ONLY functions allowed to read
deletion_requests.csv, sample_deletion_requests.csv, sample_output.csv,
user_identities.csv, user_audit_log.csv, system_activity.csv,
deletion_rules.csv and evidence_files.csv from disk. Everything else
(including code/audit/timeview.py) calls into this module instead of
opening these files itself, so there is exactly one place that knows the
CSV schema.

The three loaders TimeView reads on every construction
(load_system_activity, load_user_audit_log, load_evidence_files) are
memoized with lru_cache, since the dataset files do not change during a
run and TimeView is built once per case. Callers must not mutate the
returned list in place.
"""

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = REPO_ROOT / "dataset"


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 'Z' timestamp into a timezone-aware UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_rows(filename: str) -> list[dict]:
    path = DATASET_DIR / filename
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class DeletionRequest:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str
    reported_at: datetime
    audit_at: datetime
    request_text: str


def _row_to_deletion_request(row: dict) -> DeletionRequest:
    return DeletionRequest(
        case_id=row["case_id"],
        email=row["email"].strip().lower(),
        requested_at=parse_timestamp(row["requested_at"]),
        reported_status=row["reported_status"],
        reported_at=parse_timestamp(row["reported_at"]),
        audit_at=parse_timestamp(row["audit_at"]),
        request_text=row["request_text"],
    )


def load_deletion_requests() -> list[DeletionRequest]:
    return [_row_to_deletion_request(r) for r in _read_rows("deletion_requests.csv")]


def load_sample_deletion_requests() -> list[DeletionRequest]:
    return [_row_to_deletion_request(r) for r in _read_rows("sample_deletion_requests.csv")]


@dataclass(frozen=True)
class SampleOutputRow:
    case_id: str
    deletion_status: str
    steps: list

    @property
    def steps_json_raw(self) -> str:
        return json.dumps(self.steps, sort_keys=True, separators=(",", ":"))


def load_sample_output() -> list[SampleOutputRow]:
    rows = _read_rows("sample_output.csv")
    out = []
    for r in rows:
        steps = json.loads(r["steps_json"])
        out.append(SampleOutputRow(case_id=r["case_id"], deletion_status=r["deletion_status"], steps=steps))
    return out


@dataclass(frozen=True)
class Identity:
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime


def load_user_identities() -> list[Identity]:
    rows = _read_rows("user_identities.csv")
    return [
        Identity(
            user_id=r["user_id"],
            name=r["name"],
            email=r["email"].strip().lower(),
            phone=r["phone"],
            email_hash=r["email_hash"].strip().lower(),
            updated_at=parse_timestamp(r["updated_at"]),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class AuditLogEntry:
    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


@lru_cache(maxsize=1)
def load_user_audit_log() -> list[AuditLogEntry]:
    rows = _read_rows("user_audit_log.csv")
    return [
        AuditLogEntry(
            audit_id=r["audit_id"],
            user_id=r["user_id"],
            event_time=parse_timestamp(r["event_time"]),
            field_name=r["field_name"],
            old_value=r["old_value"],
            new_value=r["new_value"],
        )
        for r in rows
    ]


@dataclass(frozen=True)
class ActivityEntry:
    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@lru_cache(maxsize=1)
def load_system_activity() -> list[ActivityEntry]:
    rows = _read_rows("system_activity.csv")
    return [
        ActivityEntry(
            activity_id=r["activity_id"],
            event_time=parse_timestamp(r["event_time"]),
            event_type=r["event_type"],
            source_system=r["source_system"],
            target_system=r["target_system"],
            resource_id=r["resource_id"],
            reported_result=r["reported_result"],
            details=r["details"],
        )
        for r in rows
    ]


@dataclass(frozen=True)
class DeletionRule:
    rule_id: str
    data_category: str
    condition: str
    required_action: str


def load_deletion_rules() -> list[DeletionRule]:
    rows = _read_rows("deletion_rules.csv")
    return [
        DeletionRule(
            rule_id=r["rule_id"],
            data_category=r["data_category"],
            condition=r["condition"],
            required_action=r["required_action"],
        )
        for r in rows
    ]


@dataclass(frozen=True)
class EvidenceFile:
    file_id: str
    file_path: str
    origin: str
    captured_at: datetime


@lru_cache(maxsize=1)
def load_evidence_files() -> list[EvidenceFile]:
    rows = _read_rows("evidence_files.csv")
    return [
        EvidenceFile(
            file_id=r["file_id"],
            file_path=r["file_path"],
            origin=r["origin"],
            captured_at=parse_timestamp(r["captured_at"]),
        )
        for r in rows
    ]


def report_row_counts() -> dict:
    return {
        "deletion_requests.csv": len(load_deletion_requests()),
        "sample_deletion_requests.csv": len(load_sample_deletion_requests()),
        "sample_output.csv": len(load_sample_output()),
        "user_identities.csv": len(load_user_identities()),
        "user_audit_log.csv": len(load_user_audit_log()),
        "system_activity.csv": len(load_system_activity()),
        "deletion_rules.csv": len(load_deletion_rules()),
        "evidence_files.csv": len(load_evidence_files()),
    }


if __name__ == "__main__":
    for name, count in report_row_counts().items():
        print(f"{name}: {count} rows")
