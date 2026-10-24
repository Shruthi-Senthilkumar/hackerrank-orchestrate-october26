import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

import pytest  # noqa: E402

from audit.paths import resolve_evidence, PathContainmentError  # noqa: E402

REAL_REL_PATH = "evidence/logs/service_events_ap_south_20260915.log"


def test_resolves_a_real_evidence_file():
    path = resolve_evidence(REAL_REL_PATH)
    assert path.is_file()
    assert path.name == "service_events_ap_south_20260915.log"


def test_rejects_parent_traversal():
    with pytest.raises(PathContainmentError):
        resolve_evidence("evidence/../../../etc/passwd")


def test_rejects_parent_traversal_inside_subdir():
    with pytest.raises(PathContainmentError):
        resolve_evidence("evidence/logs/../../../AGENTS.md")


def test_rejects_absolute_path():
    with pytest.raises(PathContainmentError):
        resolve_evidence(str(REPO_ROOT / "AGENTS.md"))


def test_rejects_windows_drive_letter():
    with pytest.raises(PathContainmentError):
        resolve_evidence(r"C:\Windows\System32\drivers\etc\hosts")


def test_rejects_backslash_path():
    with pytest.raises(PathContainmentError):
        resolve_evidence(r"evidence\logs\service_events_ap_south_20260915.log")


def test_rejects_nonexistent_file():
    with pytest.raises(PathContainmentError):
        resolve_evidence("evidence/logs/does_not_exist.log")


def test_rejects_empty_path():
    with pytest.raises(PathContainmentError):
        resolve_evidence("")


def test_rejects_symlink_escape(tmp_path, monkeypatch):
    import audit.paths as paths_module

    fake_dataset = tmp_path / "dataset"
    fake_evidence = fake_dataset / "evidence"
    fake_evidence.mkdir(parents=True)
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("nope", encoding="utf-8")

    link_path = fake_evidence / "escape_link.txt"
    try:
        link_path.symlink_to(outside_secret)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    monkeypatch.setattr(paths_module, "DATASET_DIR", fake_dataset)
    monkeypatch.setattr(paths_module, "EVIDENCE_DIR", fake_evidence.resolve())

    with pytest.raises(PathContainmentError):
        paths_module.resolve_evidence("evidence/escape_link.txt")
