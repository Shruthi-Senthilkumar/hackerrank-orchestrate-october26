import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit.loaders import EvidenceFile, load_evidence_files  # noqa: E402
from audit.paths import resolve_evidence  # noqa: E402
from audit.reconciler import find_drift  # noqa: E402

from datetime import datetime, timezone  # noqa: E402

AUDIT_AT = datetime(2099, 1, 1, tzinfo=timezone.utc)


def test_reconciler_finds_a_synthetic_drift(tmp_path):
    sql = (
        "-- Ghost Data Still Exists: point-in-time database snapshot\n"
        "-- Captured at: 2026-01-01T00:00:00Z\n"
        "-- Database topology: read_replica\n"
        "BEGIN TRANSACTION;\n"
        "CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY, email TEXT);\n"
        "INSERT INTO customer_profiles_primary VALUES('account_001','a@example.com');\n"
        "CREATE TABLE customer_profiles_read_replica (resource_id TEXT PRIMARY KEY, email TEXT);\n"
        "INSERT INTO customer_profiles_read_replica VALUES('account_001','a@example.com');\n"
        "INSERT INTO customer_profiles_read_replica VALUES('account_999','ghost@example.com');\n"
        "COMMIT;\n"
    )
    path = tmp_path / "synthetic_drift.sql"
    path.write_text(sql, encoding="utf-8")
    ev = EvidenceFile(file_id="evidence_synth", file_path=str(path), origin="test", captured_at=AUDIT_AT)

    drifts = find_drift(ev, path)
    assert len(drifts) == 1
    assert drifts[0].resource_id == "account_999"
    assert drifts[0].present_in_replica_only is True
    assert drifts[0].primary_table == "customer_profiles_primary"
    assert drifts[0].replica_table == "customer_profiles_read_replica"


def test_reconciler_no_drift_when_tables_match(tmp_path):
    sql = (
        "-- Captured at: 2026-01-01T00:00:00Z\n"
        "-- Database topology: read_replica\n"
        "BEGIN TRANSACTION;\n"
        "CREATE TABLE customer_profiles_primary (resource_id TEXT PRIMARY KEY);\n"
        "INSERT INTO customer_profiles_primary VALUES('account_001');\n"
        "CREATE TABLE customer_profiles_read_replica (resource_id TEXT PRIMARY KEY);\n"
        "INSERT INTO customer_profiles_read_replica VALUES('account_001');\n"
        "COMMIT;\n"
    )
    path = tmp_path / "synthetic_no_drift.sql"
    path.write_text(sql, encoding="utf-8")
    ev = EvidenceFile(file_id="evidence_synth", file_path=str(path), origin="test", captured_at=AUDIT_AT)
    assert find_drift(ev, path) == []


def test_reconciler_skips_inventory_shape_files_with_no_primary_table(tmp_path):
    sql = (
        "PRAGMA foreign_keys=ON;\n"
        "BEGIN TRANSACTION;\n"
        "CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT);\n"
        "INSERT INTO snapshot_scope VALUES ('account_service', '2026-01-01T00:00:00Z');\n"
        "COMMIT;\n"
    )
    path = tmp_path / "synthetic_inventory.sql"
    path.write_text(sql, encoding="utf-8")
    ev = EvidenceFile(file_id="evidence_synth", file_path=str(path), origin="test", captured_at=AUDIT_AT)
    assert find_drift(ev, path) == []


def test_reconciler_finds_real_drift_in_at_least_one_real_replica_file():
    found_any = False
    for ev in load_evidence_files():
        if not ev.file_path.endswith(".sql"):
            continue
        drifts = find_drift(ev, resolve_evidence(ev.file_path))
        if drifts:
            found_any = True
            break
    assert found_any, "expected at least one real replica file to show drift"
