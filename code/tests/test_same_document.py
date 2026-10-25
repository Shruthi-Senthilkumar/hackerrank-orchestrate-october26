import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit.evidence.pdf_parser import _same_document_signals  # noqa: E402
from audit.linker import link_observations  # noqa: E402
from audit.loaders import EvidenceFile  # noqa: E402
from audit.models import Identity  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402

T = datetime(2026, 1, 1, tzinfo=timezone.utc)

TARGET = Identity(
    user_id="user_90",
    current_name="Target Person",
    current_email="target.person@example.com",
    current_phone="",
    current_email_hash="",
    emails=frozenset({"target.person@example.com"}),
    phones=frozenset(),
    hashes=frozenset(),
)


def test_same_document_links_resource_sharing_the_targets_email():
    ev = EvidenceFile(file_id="evidence_synth", file_path="x.pdf", origin="test", captured_at=T)
    text = "Support reference CS-0001 / support_777\nContact target.person@example.com for details."
    obs, hints = _same_document_signals(text, ev)
    time_view = build_time_view(T)
    linked = link_observations(obs, TARGET, time_view, [], hints)
    rules = {l.observation.resource_id: l.rule for l in linked}
    assert rules.get("support_777") == "same_document"


def test_same_document_decoy_with_another_persons_email_does_not_link():
    ev = EvidenceFile(file_id="evidence_synth", file_path="x.pdf", origin="test", captured_at=T)
    text = "Support reference CS-0002 / support_888\nContact someone.else@example.com for details."
    obs, hints = _same_document_signals(text, ev)
    time_view = build_time_view(T)
    linked = link_observations(obs, TARGET, time_view, [], hints)
    assert linked == []


def test_same_document_requires_both_a_resource_id_shape_and_an_identifier():
    ev = EvidenceFile(file_id="evidence_synth", file_path="x.pdf", origin="test", captured_at=T)
    obs, hints = _same_document_signals("Just some prose, no resource id, no email.", ev)
    assert obs == [] and hints == []
    obs2, hints2 = _same_document_signals("support_999 appears here with no identifier at all.", ev)
    assert obs2 == [] and hints2 == []
