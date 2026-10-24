import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import loaders  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402


def test_is_visible_inclusive_boundary():
    requests = loaders.load_sample_deletion_requests()
    audit_at = requests[0].audit_at
    view = build_time_view(audit_at)
    assert view.is_visible(audit_at) is True
    assert view.is_visible(audit_at - timedelta(seconds=1)) is True
    assert view.is_visible(audit_at + timedelta(seconds=1)) is False


def test_visible_activity_never_exceeds_audit_at():
    audit_at = loaders.load_deletion_requests()[0].audit_at
    view = build_time_view(audit_at)
    for a in view.visible_activity():
        assert a.event_time <= audit_at


def test_visible_audit_log_never_exceeds_audit_at():
    audit_at = loaders.load_deletion_requests()[0].audit_at
    view = build_time_view(audit_at)
    for entry in view.visible_audit_log():
        assert entry.event_time <= audit_at


def test_visible_evidence_files_never_exceeds_audit_at():
    audit_at = loaders.load_deletion_requests()[0].audit_at
    view = build_time_view(audit_at)
    for ev in view.visible_evidence_files():
        assert ev.captured_at <= audit_at


def test_no_future_evidence_leaks_across_all_518_plus_32_requests():
    """The mandated full sweep: for every case's audit_at, nothing visible
    through TimeView (activity, audit log, evidence manifest) is ever
    stamped after that audit_at."""
    all_requests = loaders.load_deletion_requests() + loaders.load_sample_deletion_requests()
    assert len(all_requests) == 518 + 32

    distinct_audit_ats = sorted({r.audit_at for r in all_requests})
    violations = []
    for audit_at in distinct_audit_ats:
        view = build_time_view(audit_at)
        for a in view.visible_activity():
            if a.event_time > audit_at:
                violations.append(("activity", a.activity_id, a.event_time, audit_at))
        for entry in view.visible_audit_log():
            if entry.event_time > audit_at:
                violations.append(("audit_log", entry.audit_id, entry.event_time, audit_at))
        for ev in view.visible_evidence_files():
            if ev.captured_at > audit_at:
                violations.append(("evidence", ev.file_id, ev.captured_at, audit_at))

    assert violations == []


def test_visible_sets_are_proper_subsets_of_raw_tables():
    audit_at = loaders.load_sample_deletion_requests()[0].audit_at
    view = build_time_view(audit_at)
    assert len(view.visible_activity()) <= len(loaders.load_system_activity())
    assert len(view.visible_audit_log()) <= len(loaders.load_user_audit_log())
    assert len(view.visible_evidence_files()) <= len(loaders.load_evidence_files())
