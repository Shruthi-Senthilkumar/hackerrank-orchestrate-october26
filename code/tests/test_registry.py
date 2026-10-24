import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit.evidence.registry import build_registry, visible_observations, visible_coverage  # noqa: E402
from audit.loaders import load_evidence_files  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402


def test_every_evidence_file_is_parsed_or_explicitly_deferred():
    reg = build_registry()
    assert len(reg.parse_table) == len(load_evidence_files()) == 94
    assert reg.errors == []
    image_rows = [r for r in reg.parse_table if r["format"] == "image"]
    assert len(image_rows) == 11
    assert all(r["observations"] == 0 for r in image_rows)  # deferred to Phase 4, not guessed


def test_registry_produces_a_large_nonzero_observation_and_coverage_set():
    reg = build_registry()
    assert len(reg.all_observations()) > 2000
    assert len(reg.all_coverage()) > 100


def test_visible_observations_respects_manifest_time_not_future_files():
    reg = build_registry()
    early_cutoff = build_time_view(datetime(2026, 1, 5, tzinfo=timezone.utc))
    late_cutoff = build_time_view(datetime(2099, 1, 1, tzinfo=timezone.utc))

    early_obs = visible_observations(reg, early_cutoff)
    late_obs = visible_observations(reg, late_cutoff)
    assert len(early_obs) < len(late_obs)
    for o in early_obs:
        assert o.manifest_time <= early_cutoff.audit_at


def test_visible_coverage_respects_manifest_time():
    reg = build_registry()
    cutoff = build_time_view(datetime(2026, 3, 1, tzinfo=timezone.utc))
    cov = visible_coverage(reg, cutoff)
    visible_file_ids = {e.file_id for e in cutoff.visible_evidence_files()}
    for file_id, cov_list in reg.coverage_by_file.items():
        if file_id in visible_file_ids:
            for c in cov_list:
                assert c in cov
