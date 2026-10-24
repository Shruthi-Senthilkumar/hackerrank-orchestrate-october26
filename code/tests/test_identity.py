import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import identity, loaders  # noqa: E402


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_as_of_reconstruction_undoes_events_after_audit_at(monkeypatch):
    """A synthetic user with two phone-number changes: one before
    audit_at (must be kept, i.e. folded into the held set) and one
    after (must be undone, i.e. never appear as the as-of value and
    never leak into the held set as something that existed by
    audit_at)."""
    import audit.identity as identity_mod

    class FakeEntry:
        def __init__(self, user_id, event_time, field_name, old_value, new_value):
            self.user_id = user_id
            self.event_time = event_time
            self.field_name = field_name
            self.old_value = old_value
            self.new_value = new_value

    fake_log = [
        FakeEntry("user_synth", _ts("2026-01-01T00:00:00Z"), "phone", "+1-000", "+1-111"),  # before audit_at
        FakeEntry("user_synth", _ts("2026-06-01T00:00:00Z"), "phone", "+1-111", "+1-222"),  # after audit_at
    ]

    class FakeIdentity:
        user_id = "user_synth"
        name = "Synthetic Person"
        email = "synth@example.com"
        phone = "+1-222"  # current snapshot: reflects the post-audit_at change
        email_hash = hashlib.sha256(b"synth@example.com").hexdigest()

    monkeypatch.setattr(identity_mod.timeview, "all_audit_log_entries", lambda: fake_log)
    monkeypatch.setattr(identity_mod, "_identities_by_user_id", lambda: {"user_synth": FakeIdentity()})
    identity_mod._events_by_user_field.cache_clear()

    audit_at = _ts("2026-03-01T00:00:00Z")  # between the two phone changes
    ident = identity_mod.build_identity("user_synth", audit_at)

    assert ident.current_phone == "+1-111"  # the undone (correct, as-of-audit_at) value
    assert "+1-111" in ident.phones  # held at audit_at
    assert "+1-222" not in ident.phones  # the post-audit_at value must never leak in

    identity_mod._events_by_user_field.cache_clear()


def test_as_of_reconstruction_keeps_earlier_value_with_no_relevant_events_yet(monkeypatch):
    """If the only event for a field happens after audit_at, the value at
    audit_at is that event's old_value (unchanged since before), not the
    current snapshot value."""
    import audit.identity as identity_mod

    class FakeEntry:
        def __init__(self, user_id, event_time, field_name, old_value, new_value):
            self.user_id = user_id
            self.event_time = event_time
            self.field_name = field_name
            self.old_value = old_value
            self.new_value = new_value

    fake_log = [FakeEntry("user_synth2", _ts("2026-06-01T00:00:00Z"), "phone", "+1-ORIGINAL", "+1-NEW")]

    class FakeIdentity:
        user_id = "user_synth2"
        name = "Synthetic Person Two"
        email = "synth2@example.com"
        phone = "+1-NEW"
        email_hash = hashlib.sha256(b"synth2@example.com").hexdigest()

    monkeypatch.setattr(identity_mod.timeview, "all_audit_log_entries", lambda: fake_log)
    monkeypatch.setattr(identity_mod, "_identities_by_user_id", lambda: {"user_synth2": FakeIdentity()})
    identity_mod._events_by_user_field.cache_clear()

    audit_at = _ts("2026-01-01T00:00:00Z")  # before the only event
    ident = identity_mod.build_identity("user_synth2", audit_at)

    assert ident.current_phone == "+1-ORIGINAL"
    assert ident.phones == frozenset({"+1-ORIGINAL"})

    identity_mod._events_by_user_field.cache_clear()


def test_email_hash_matches_sha256_for_every_real_identity():
    for ident in loaders.load_user_identities():
        expected = hashlib.sha256(ident.email.encode("utf-8")).hexdigest()
        assert ident.email_hash == expected


def test_all_518_plus_32_request_emails_resolve():
    all_requests = loaders.load_deletion_requests() + loaders.load_sample_deletion_requests()
    stats = identity.report_identity_statistics(all_requests)
    assert stats["total"] == 550
    assert stats["unresolved_case_ids"] == [], (
        f"{len(stats['unresolved_case_ids'])} request emails did not resolve: "
        f"{stats['unresolved_case_ids'][:10]}"
    )
    assert stats["resolved"] == 550
