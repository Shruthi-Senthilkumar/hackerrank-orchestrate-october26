"""Repo-root-relative path resolution with containment inside dataset/evidence/.

F01. This is the only place allowed to turn a string from a CSV or JSON
record into a filesystem path. Every evidence read must go through
`resolve_evidence`.
"""

from pathlib import Path, PureWindowsPath

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = (DATASET_DIR / "evidence").resolve()


class PathContainmentError(ValueError):
    """Raised when a candidate path would resolve outside dataset/evidence/."""


def resolve_evidence(rel_path: str) -> Path:
    """Resolve `rel_path` (as stored in the evidence manifest) to a real file.

    Returns the resolved Path only if it is inside dataset/evidence/.
    Rejects "..", absolute paths, Windows drive letters, backslashes, and
    symlink escapes. Raises PathContainmentError on any violation,
    including a target that does not exist or is not a regular file.
    """
    if rel_path is None or rel_path == "":
        raise PathContainmentError("empty path")

    if "\\" in rel_path:
        raise PathContainmentError(f"backslash not allowed in evidence path: {rel_path!r}")

    if PureWindowsPath(rel_path).drive:
        raise PathContainmentError(f"drive letter not allowed in evidence path: {rel_path!r}")

    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise PathContainmentError(f"absolute path not allowed: {rel_path!r}")

    parts = candidate.parts
    if ".." in parts:
        raise PathContainmentError(f"parent traversal not allowed: {rel_path!r}")

    # rel_path is stored as "evidence/<subdir>/<file>"; accept that prefix
    # or a path already relative to dataset/evidence/.
    if parts and parts[0] == "evidence":
        full = (DATASET_DIR / candidate).resolve()
    else:
        full = (EVIDENCE_DIR / candidate).resolve()

    try:
        full.relative_to(EVIDENCE_DIR)
    except ValueError:
        raise PathContainmentError(
            f"resolved path escapes dataset/evidence/: {rel_path!r} -> {full}"
        )

    if not full.exists():
        raise PathContainmentError(f"evidence file does not exist: {rel_path!r} -> {full}")
    if not full.is_file():
        raise PathContainmentError(f"evidence path is not a regular file: {rel_path!r} -> {full}")

    return full
