"""Final-phase task 8: builds submission/code.zip (README.md at the
zip root + code/) and runs the 7 SUBMISSION.md section 4 preflight
checks, refusing to continue on any failure.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

SUBMISSION_DIR = REPO_ROOT / "submission"
MAX_ZIP_MB = 40

EXCLUDE_DIR_NAMES = {
    "dataset", ".venv", "venv", "__pycache__", ".pytest_cache", ".cache", ".git",
    "claude_terminal", "node_modules",
}
EXCLUDE_FILES = {".env", "output.csv", "log.txt", "PRD.md"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}

_SECRET_RES = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"api_key\s*=\s*[\"']?[A-Za-z0-9_-]{16,}"),
]


def fail(msg: str) -> None:
    print(f"PREFLIGHT FAILED: {msg}")
    raise SystemExit(1)


def check_1_output_csv() -> None:
    import csv

    path = REPO_ROOT / "output.csv"
    if not path.exists():
        fail("output.csv missing")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        fail("output.csv has a BOM")
    if b"\r\n" in raw:
        fail("output.csv has CRLF line endings")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if list(rows[0].keys()) if False else None:
        pass
    with open(path, encoding="utf-8") as f:
        header = f.readline().strip()
    if header != "case_id,deletion_status,steps_json":
        fail(f"output.csv header wrong: {header!r}")
    if len(rows) != 518:
        fail(f"output.csv has {len(rows)} data rows, expected 518")
    case_ids = [r["case_id"] for r in rows]
    if case_ids != sorted(case_ids):
        fail("output.csv rows not sorted by case_id")
    for r in rows:
        if r["deletion_status"] not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            fail(f"{r['case_id']}: invalid deletion_status {r['deletion_status']!r}")
        steps = json.loads(r["steps_json"])
        if r["deletion_status"] == "NOT_APPLICABLE" and steps != []:
            fail(f"{r['case_id']}: NOT_APPLICABLE must have steps=[]")
        for i, step in enumerate(steps, start=1):
            if step["step_no"] != i:
                fail(f"{r['case_id']}: step_no not consecutive from 1")
    print("check 1 PASS: output.csv valid, 518 rows, sorted, UTF-8/LF/no-BOM")


def check_2_reports() -> None:
    for name in ("evaluation_report.md", "usage_report.md"):
        path = REPO_ROOT / "code" / "evaluation" / name
        if not path.exists():
            fail(f"{name} missing")
        text = path.read_text(encoding="utf-8")
        if "STATUS: PLACEHOLDER" in text:
            fail(f"{name} still has a placeholder line")
        if len(text.strip()) < 200:
            fail(f"{name} looks too short to be real")
    print("check 2 PASS: both evaluation reports exist and are not placeholders")


def check_3_readme() -> None:
    path = REPO_ROOT / "README.md"
    if not path.exists():
        fail("README.md missing")
    text = path.read_text(encoding="utf-8")
    for needle in ("Setup", "Run", "Approach overview"):
        if needle not in text:
            fail(f"README.md missing a '{needle}' section")
    print("check 3 PASS: README.md has setup, run, and approach-overview sections")


def _iter_zip_sources():
    yield (REPO_ROOT / "README.md"), "README.md"
    code_dir = REPO_ROOT / "code"
    for path in code_dir.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            continue
        yield path, str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def check_4_build_zip() -> Path:
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = SUBMISSION_DIR / "code.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in _iter_zip_sources():
            zf.write(src, arcname)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_ZIP_MB:
        fail(f"code.zip is {size_mb:.1f} MB, over the {MAX_ZIP_MB} MB internal cap")
    names = zipfile.ZipFile(zip_path).namelist()
    if "README.md" not in names:
        fail("README.md missing from zip root")
    if not any(n.startswith("code/evaluation/evaluation_report.md") for n in names):
        fail("evaluation_report.md missing from zip")
    if not any(n.startswith("code/evaluation/usage_report.md") for n in names):
        fail("usage_report.md missing from zip")
    for n in names:
        if Path(n).suffix.lower() in ARCHIVE_SUFFIXES:
            fail(f"nested archive found in zip: {n}")
    print(f"check 4 PASS: code.zip built, {size_mb:.1f} MB, README at root, code/ present, no nested archives")
    return zip_path


def check_5_secret_scan(zip_path: Path) -> None:
    hits = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith((".md", ".py", ".json")):
                try:
                    text = zf.read(name).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                for pat in _SECRET_RES:
                    if pat.search(text):
                        hits += 1
    log_text = (REPO_ROOT / "log.txt").read_text(encoding="utf-8", errors="ignore") if (REPO_ROOT / "log.txt").exists() else ""
    for pat in _SECRET_RES:
        if pat.search(log_text):
            hits += 1
    if hits:
        fail(f"secret scan found {hits} secret-shaped pattern(s)")
    print("check 5 PASS: secret scan of zip + log.txt found 0 matches")


def check_6_log_check() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "claude_terminal" / "log_tools.py"), "check"],
        capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        fail("log_tools.py check failed")
    print("check 6 PASS: log_tools.py check passed")


def check_7_clean_reproduction() -> None:
    scratch = REPO_ROOT / ".cache" / "scratch" / "clean_repro"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    code_dst = scratch / "code"
    shutil.copytree(REPO_ROOT / "code", code_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(REPO_ROOT / "dataset", scratch / "dataset")

    env = {"PATH": __import__("os").environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, str(code_dst / "main.py"), "--no-ai"],
        cwd=scratch, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        fail("clean-checkout --no-ai run did not exit 0 with no keys in the environment")

    committed = (REPO_ROOT / "output.csv").read_bytes()
    reproduced = (scratch / "output.csv").read_bytes()
    if hashlib.sha256(committed).hexdigest() != hashlib.sha256(reproduced).hexdigest():
        fail("clean-checkout output.csv does not match the committed one byte for byte")
    shutil.rmtree(scratch)
    print("check 7 PASS: clean checkout (no keys, no .cache/) reproduces output.csv byte for byte")


def main() -> int:
    check_1_output_csv()
    check_2_reports()
    check_3_readme()
    zip_path = check_4_build_zip()
    check_5_secret_scan(zip_path)
    check_6_log_check()
    check_7_clean_reproduction()

    shutil.copy2(REPO_ROOT / "output.csv", SUBMISSION_DIR / "output.csv")
    print("\nAll 7 preflight checks PASS.")
    print(f"submission/code.zip: {(SUBMISSION_DIR / 'code.zip').stat().st_size / 1024 / 1024:.1f} MB")
    print(f"submission/output.csv: {(SUBMISSION_DIR / 'output.csv').stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
