import sys
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import loaders  # noqa: E402


def test_row_counts_match_dataset_contract():
    assert len(loaders.load_deletion_requests()) == 518
    assert len(loaders.load_sample_deletion_requests()) == 32
    assert len(loaders.load_sample_output()) == 32
    assert len(loaders.load_user_identities()) == 850
    assert len(loaders.load_user_audit_log()) == 306
    assert len(loaders.load_system_activity()) == 4011
    assert len(loaders.load_deletion_rules()) == 15
    assert len(loaders.load_evidence_files()) == 94


def test_timestamps_are_timezone_aware_utc():
    req = loaders.load_deletion_requests()[0]
    for ts in (req.requested_at, req.reported_at, req.audit_at):
        assert ts.tzinfo is not None
        assert ts.tzinfo == timezone.utc or ts.utcoffset().total_seconds() == 0


def test_emails_are_lowercased_and_trimmed():
    for req in loaders.load_deletion_requests():
        assert req.email == req.email.strip().lower()
    for ident in loaders.load_user_identities():
        assert ident.email == ident.email.strip().lower()


def test_email_hash_matches_sha256_of_email():
    import hashlib

    for ident in loaders.load_user_identities():
        expected = hashlib.sha256(ident.email.encode("utf-8")).hexdigest()
        assert ident.email_hash == expected


def test_sample_output_steps_round_trip_to_valid_json_array():
    for row in loaders.load_sample_output():
        assert isinstance(row.steps, list)
        for step in row.steps:
            assert "step_no" in step
            assert "phase" in step
            assert "operation" in step


def test_cached_loaders_return_consistent_data_across_calls():
    first = loaders.load_system_activity()
    second = loaders.load_system_activity()
    assert len(first) == len(second) == 4011
