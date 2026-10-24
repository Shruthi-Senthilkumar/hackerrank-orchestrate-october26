"""F07 replica drift reconciler (PRD 7.5, decision D5).

Only the 13 "two-table" SQL snapshots (a *_primary table plus one or
more differently-named replica tables in the same file) can show
replica drift; the 11 "inventory" snapshots have no primary/replica
pair. For each such file, a resource_id present in a replica table but
missing from the primary (or vice versa) is reported as a ReplicaDrift
fact. This module makes no policy decision about what drift means.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audit.evidence.sql_sandbox import load_sql_file
    from audit.loaders import EvidenceFile
else:
    from .evidence.sql_sandbox import load_sql_file
    from .loaders import EvidenceFile


@dataclass(frozen=True)
class ReplicaDrift:
    file_id: str
    primary_table: str
    replica_table: str
    resource_id: str
    present_in_replica_only: bool  # False means present in primary only


def find_drift(ev: EvidenceFile, resolved_path: Path) -> list[ReplicaDrift]:
    snap = load_sql_file(resolved_path)
    try:
        tables = snap.tables()
        primary = next((t for t in tables if t.endswith("_primary")), None)
        if primary is None:
            return []  # inventory shape, or a primary-only file with no replica to compare

        primary_ids = {row["resource_id"] for row in snap.rows_as_dicts(primary)}
        drifts: list[ReplicaDrift] = []
        for replica in tables:
            if replica == primary:
                continue
            replica_ids = {row["resource_id"] for row in snap.rows_as_dicts(replica)}
            for rid in sorted(replica_ids - primary_ids):
                drifts.append(ReplicaDrift(ev.file_id, primary, replica, rid, True))
            for rid in sorted(primary_ids - replica_ids):
                drifts.append(ReplicaDrift(ev.file_id, primary, replica, rid, False))
        return drifts
    finally:
        snap.close()
