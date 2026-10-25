"""Evidence registry (F04): walks the manifest once, dispatches every
file to its format parser, and caches the normalized result on disk.

This module is intentionally exempt from the "only loaders.py/timeview.py
reads the raw evidence manifest" gateway rule (see
code/tests/test_gateway_rule.py's ALLOWED_FILES): per PRD section 7.2,
evidence ingestion is a single global pass over every evidence file, run
once before any case loop, independent of any one case's audit_at. The
per-case time filter is applied downstream, by `visible_observations`,
which only ever consults `TimeView.visible_evidence_files()` to decide
which already-parsed file_ids a given case may use. No decision logic
anywhere else may skip that filter.
"""

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit import loaders, paths
    from audit.evidence import json_parser, log_parser, pdf_parser, sql_parser, text_parser
    from audit.evidence.sql_sandbox import SqlSandboxError
    from audit.models import Coverage, DocumentHint, Observation, TraceHint
    from audit.timeview import TimeView
else:
    from .. import loaders, paths
    from . import json_parser, log_parser, pdf_parser, sql_parser, text_parser
    from .sql_sandbox import SqlSandboxError
    from ..models import Coverage, DocumentHint, Observation, TraceHint
    from ..timeview import TimeView

CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".cache"
CACHE_PATH = CACHE_DIR / "evidence_registry.json"

_FORMAT_BY_SUFFIX = {
    ".sql": "sql",
    ".json": "json",
    ".log": "log",
    ".txt": "text",
    ".pdf": "pdf",
    ".png": "image",
}


class RegistryError(RuntimeError):
    """Raised when an evidence file has an unknown or unparseable format."""


def _format_for_path(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix not in _FORMAT_BY_SUFFIX:
        raise RegistryError(f"unknown evidence format (suffix {suffix!r}) for {file_path}")
    return _FORMAT_BY_SUFFIX[suffix]


def _parse_one(
    ev: loaders.EvidenceFile,
) -> tuple[list[Observation], list[Coverage], list[TraceHint], list[DocumentHint], int, str]:
    """Returns (observations, coverage, trace_hints, document_hints, unparsed_count, format)."""
    fmt = _format_for_path(ev.file_path)
    resolved = paths.resolve_evidence(ev.file_path)

    if fmt == "sql":
        obs, cov = sql_parser.parse_sql_file(ev, resolved)
        return obs, cov, [], [], 0, fmt
    if fmt == "json":
        obs, cov = json_parser.parse_json_file(ev, resolved)
        return obs, cov, [], [], 0, fmt
    if fmt == "log":
        obs, unparsed, hints = log_parser.parse_log_file(ev, resolved)
        return obs, [], hints, [], unparsed, fmt
    if fmt == "text":
        obs, _snapshot_ts = text_parser.parse_text_file(ev, resolved)
        return obs, [], [], [], 0, fmt
    if fmt == "pdf":
        obs, _info, doc_hints = pdf_parser.parse_pdf_file(ev, resolved)
        return obs, [], [], doc_hints, 0, fmt
    if fmt == "image":
        # Images are not read in Phase 2; deferred to Phase 4's vision model.
        return [], [], [], [], 0, fmt

    raise RegistryError(f"no parser dispatch for format {fmt!r} ({ev.file_path})")  # pragma: no cover


def _observation_to_dict(obs: Observation) -> dict:
    d = asdict(obs)
    d["manifest_time"] = obs.manifest_time.isoformat()
    d["observed_at"] = obs.observed_at.isoformat()
    d["identifiers_present"] = sorted(obs.identifiers_present)
    d["link_keys"] = sorted(obs.link_keys)
    d["references"] = sorted(obs.references)
    return d


def _observation_from_dict(d: dict) -> Observation:
    return Observation(
        system_id=d["system_id"],
        resource_id=d["resource_id"],
        category=d["category"],
        store=d["store"],
        source_id=d["source_id"],
        manifest_time=datetime.fromisoformat(d["manifest_time"]),
        observed_at=datetime.fromisoformat(d["observed_at"]),
        exists=d["exists"],
        identifiers_present=frozenset(d["identifiers_present"]),
        attrs=d["attrs"],
        link_keys=frozenset(d["link_keys"]),
        references=frozenset(d.get("references", [])),
    )


def _coverage_to_dict(cov: Coverage) -> dict:
    d = asdict(cov)
    d["observed_at"] = cov.observed_at.isoformat()
    return d


def _coverage_from_dict(d: dict) -> Coverage:
    return Coverage(
        store=d["store"], collection=d["collection"], observed_at=datetime.fromisoformat(d["observed_at"]),
        source_id=d["source_id"], scoped=d.get("scoped", False),
    )


def _trace_hint_to_dict(hint: TraceHint) -> dict:
    d = asdict(hint)
    d["event_time"] = hint.event_time.isoformat()
    return d


def _trace_hint_from_dict(d: dict) -> TraceHint:
    return TraceHint(
        trace_id=d["trace_id"],
        value=d["value"],
        event_time=datetime.fromisoformat(d["event_time"]),
        source_id=d["source_id"],
    )


def _document_hint_to_dict(hint: DocumentHint) -> dict:
    d = asdict(hint)
    d["event_time"] = hint.event_time.isoformat()
    return d


def _document_hint_from_dict(d: dict) -> DocumentHint:
    return DocumentHint(
        document_id=d["document_id"],
        value=d["value"],
        event_time=datetime.fromisoformat(d["event_time"]),
        source_id=d["source_id"],
    )


def _cache_key() -> str:
    h = hashlib.sha256()
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_id):
        h.update(ev.file_id.encode("utf-8"))
        try:
            h.update(paths.resolve_evidence(ev.file_path).read_bytes())
        except paths.PathContainmentError:
            h.update(b"MISSING")
    for mod_path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(mod_path.read_bytes())
    return h.hexdigest()


class RegistryResult:
    def __init__(self):
        self.observations_by_file: dict[str, list[Observation]] = {}
        self.coverage_by_file: dict[str, list[Coverage]] = {}
        self.trace_hints_by_file: dict[str, list[TraceHint]] = {}
        self.document_hints_by_file: dict[str, list[DocumentHint]] = {}
        self.parse_table: list[dict] = []
        self.errors: list[dict] = []

    def all_observations(self) -> list[Observation]:
        out = []
        for obs_list in self.observations_by_file.values():
            out.extend(obs_list)
        return out

    def all_coverage(self) -> list[Coverage]:
        out = []
        for cov_list in self.coverage_by_file.values():
            out.extend(cov_list)
        return out

    def all_trace_hints(self) -> list[TraceHint]:
        out = []
        for hint_list in self.trace_hints_by_file.values():
            out.extend(hint_list)
        return out

    def all_document_hints(self) -> list[DocumentHint]:
        out = []
        for hint_list in self.document_hints_by_file.values():
            out.extend(hint_list)
        return out


def build_registry(use_cache: bool = True) -> RegistryResult:
    cache_key = _cache_key()
    if use_cache and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("cache_key") == cache_key:
                result = RegistryResult()
                for file_id, obs_list in cached["observations_by_file"].items():
                    result.observations_by_file[file_id] = [_observation_from_dict(d) for d in obs_list]
                for file_id, cov_list in cached["coverage_by_file"].items():
                    result.coverage_by_file[file_id] = [_coverage_from_dict(d) for d in cov_list]
                for file_id, hint_list in cached.get("trace_hints_by_file", {}).items():
                    result.trace_hints_by_file[file_id] = [_trace_hint_from_dict(d) for d in hint_list]
                for file_id, hint_list in cached.get("document_hints_by_file", {}).items():
                    result.document_hints_by_file[file_id] = [_document_hint_from_dict(d) for d in hint_list]
                result.parse_table = cached["parse_table"]
                result.errors = cached["errors"]
                return result
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # fall through and rebuild

    result = RegistryResult()
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_id):
        try:
            obs, cov, hints, doc_hints, unparsed, fmt = _parse_one(ev)
        except (RegistryError, SqlSandboxError, ValueError, json.JSONDecodeError) as e:
            result.errors.append({"file_id": ev.file_id, "file_path": ev.file_path, "error": str(e)})
            result.parse_table.append(
                {
                    "file_id": ev.file_id,
                    "format": "ERROR",
                    "observations": 0,
                    "coverage": 0,
                    "unparsed": 0,
                }
            )
            continue
        result.observations_by_file[ev.file_id] = obs
        result.coverage_by_file[ev.file_id] = cov
        result.trace_hints_by_file[ev.file_id] = hints
        result.document_hints_by_file[ev.file_id] = doc_hints
        result.parse_table.append(
            {
                "file_id": ev.file_id,
                "format": fmt,
                "observations": len(obs),
                "coverage": len(cov),
                "unparsed": unparsed,
            }
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "observations_by_file": {
                    fid: [_observation_to_dict(o) for o in obs] for fid, obs in result.observations_by_file.items()
                },
                "coverage_by_file": {
                    fid: [_coverage_to_dict(c) for c in cov] for fid, cov in result.coverage_by_file.items()
                },
                "trace_hints_by_file": {
                    fid: [_trace_hint_to_dict(h) for h in hints]
                    for fid, hints in result.trace_hints_by_file.items()
                },
                "document_hints_by_file": {
                    fid: [_document_hint_to_dict(h) for h in hints]
                    for fid, hints in result.document_hints_by_file.items()
                },
                "parse_table": result.parse_table,
                "errors": result.errors,
            },
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return result


def visible_observations(result: RegistryResult, time_view: TimeView) -> list[Observation]:
    """Every Observation whose source evidence file is visible at this
    TimeView's audit_at (D15: gated by the file's manifest captured_at,
    never by an observation's own observed_at)."""
    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    out = []
    for file_id, obs_list in result.observations_by_file.items():
        if file_id in visible_file_ids:
            out.extend(obs_list)
    return out


def visible_coverage(result: RegistryResult, time_view: TimeView) -> list[Coverage]:
    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    out = []
    for file_id, cov_list in result.coverage_by_file.items():
        if file_id in visible_file_ids:
            out.extend(cov_list)
    return out


def visible_trace_hints(result: RegistryResult, time_view: TimeView) -> list[TraceHint]:
    """Every TraceHint whose file is visible AND whose own line's
    event_time is <= audit_at (a stricter, line-level check on top of
    the file-level gate, specific to trace_correlation: see
    code/audit/linker.py)."""
    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    out = []
    for file_id, hint_list in result.trace_hints_by_file.items():
        if file_id not in visible_file_ids:
            continue
        for hint in hint_list:
            if time_view.is_visible(hint.event_time):
                out.append(hint)
    return out


def visible_document_hints(result: RegistryResult, time_view: TimeView) -> list[DocumentHint]:
    """Every DocumentHint whose file is visible AND whose own event_time
    (the document's manifest time) is <= audit_at. See
    code/audit/linker.py's same_document rule."""
    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    out = []
    for file_id, hint_list in result.document_hints_by_file.items():
        if file_id not in visible_file_ids:
            continue
        for hint in hint_list:
            if time_view.is_visible(hint.event_time):
                out.append(hint)
    return out


if __name__ == "__main__":
    reg = build_registry()
    for row in reg.parse_table:
        print(f"{row['file_id']:12s} {row['format']:6s} obs={row['observations']:4d} "
              f"cov={row['coverage']:3d} unparsed={row['unparsed']}")
    if reg.errors:
        print("\nERRORS:")
        for e in reg.errors:
            print(" ", e)
    print(f"\nTotal: {len(reg.all_observations())} observations, {len(reg.all_coverage())} coverage records, "
          f"{len(reg.all_trace_hints())} trace hints, {len(reg.all_document_hints())} document hints, "
          f"{len(reg.errors)} errors")
