"""F02 gateway rule: only code/audit/timeview.py and code/audit/loaders.py
may reference the raw time-dependent tables (system_activity.csv,
user_audit_log.csv, evidence_files.csv) or the loader functions that read
them. Every other module under code/audit/ must go through TimeView for
any per-case, audit_at-bounded decision.

code/audit/evidence/registry.py is the one other exemption: per PRD
section 7.2, evidence ingestion is a single global pass over every
evidence file, run once before any case loop, independent of any one
case's audit_at (see its own module docstring). It calls
load_evidence_files() directly to enumerate every file once; the
per-case time filter is enforced downstream by its
`visible_observations`/`visible_coverage`, which only ever consult
`TimeView.visible_evidence_files()`. No other module may take this
shortcut.

This is a static-analysis test: it greps source files rather than running
them, so a future module cannot "accidentally" bypass the gateway without
this test failing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR = REPO_ROOT / "code" / "audit"

GUARDED_LOADER_CALLS = [
    "load_system_activity",
    "load_user_audit_log",
    "load_evidence_files",
]
GUARDED_FILENAMES = [
    "system_activity.csv",
    "user_audit_log.csv",
    "evidence_files.csv",
]

ALLOWED_FILES = {
    AUDIT_DIR / "loaders.py",
    AUDIT_DIR / "timeview.py",
    AUDIT_DIR / "evidence" / "registry.py",
}


def _all_audit_py_files():
    return [p for p in AUDIT_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_module_outside_gateway_calls_guarded_loaders():
    violations = []
    for path in _all_audit_py_files():
        if path in ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for name in GUARDED_LOADER_CALLS:
            if re.search(rf"\b{name}\s*\(", text):
                violations.append(f"{path.relative_to(REPO_ROOT)} calls {name}()")
    assert violations == [], "\n".join(violations)


def test_no_module_outside_gateway_names_guarded_filenames():
    violations = []
    for path in _all_audit_py_files():
        if path in ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for fname in GUARDED_FILENAMES:
            if fname in text:
                violations.append(f"{path.relative_to(REPO_ROOT)} references {fname}")
    assert violations == [], "\n".join(violations)


def test_timeview_itself_only_uses_loaders_module():
    """timeview.py may call the guarded loaders (it IS the gateway) but
    must not open any dataset file directly itself."""
    text = (AUDIT_DIR / "timeview.py").read_text(encoding="utf-8")
    assert "open(" not in text
    assert ".csv" not in text
