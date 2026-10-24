"""Parser for the 26 .log evidence files (F04), covering all 10 families
found in Phase 1 profiling (corrected grouping; see
code/evaluation/profile_report.md section 5 for the correction from an
earlier over-split into 15-16 "families").

Every line is treated as untrusted data: it is matched against one of a
small set of known line shapes and its key=value fields extracted; a
value is never evaluated or allowed to change parser behavior, no matter
what text it contains (no eval/exec, no string formatting of a value
back into code). A line whose shape does not match its family's known
patterns is counted as unparsed and reported, never guessed at.

Logs do not get blanket Coverage records the way a database or JSON
snapshot does: a log is a stream of individual events, not a dump of a
whole collection, so it can only prove the state of the exact
resource_id a line mentions, which a plain Observation already covers.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit import mapping
    from audit.loaders import EvidenceFile
    from audit.models import Observation
else:
    from .. import mapping
    from ..loaders import EvidenceFile
    from ..models import Observation

#: The 10 real log-file families, by filename stem. This is the
#: canonical definition; code/tools/profile_dataset.py imports
#: family_for_filename from here instead of keeping its own copy.
LOG_FAMILY_STEMS = [
    "application_trace",
    "cloud_runtime_export",
    "notification_delivery",
    "operations_stream",
    "resource_lookup_trace",
    "search_index_diagnostic",
    "service_events",
    "structured_service_events",
    "support_replica",
    "syslog_archive",
]


def family_for_filename(fname: str) -> str:
    for stem in LOG_FAMILY_STEMS:
        if fname.startswith(stem):
            return stem
    return "unknown"


_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(.*)$")
_KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _unquote(value: str) -> str:
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _extract_kv(text: str) -> dict[str, str]:
    return {k: _unquote(v) for k, v in _KV_RE.findall(text)}


def _parse_application_trace(rest: str) -> dict | None:
    m = re.match(r"^\[(\w+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*(\w+):\s*(.*)$", rest)
    if not m:
        return None
    level, component, trace_id, event, tail = m.groups()
    fields = _extract_kv(tail)
    fields.update(level=level, component=component, trace_id=trace_id, event=event)
    return fields


def _parse_cloud_runtime_export(rest: str) -> dict | None:
    outer = _extract_kv(rest)
    if "message" not in outer:
        return None
    inner = _extract_kv(outer.pop("message"))
    outer.update(inner)
    return outer


def _parse_bare_level_kv(rest: str) -> dict | None:
    m = re.match(r"^(\w+)\s+(.*)$", rest)
    if not m:
        return None
    level, tail = m.groups()
    fields = _extract_kv(tail)
    if not fields:
        return None
    fields["level"] = level
    return fields


def _parse_operations_stream(rest: str) -> dict | None:
    parts = [p.strip() for p in rest.split("|")]
    if len(parts) < 4:
        return None
    level, component, trace_id, event = parts[0], parts[1], parts[2], parts[3]
    tail = "|".join(parts[4:])
    fields = _extract_kv(tail)
    fields.update(level=level, component=component, trace_id=trace_id, event=event)
    return fields


def _parse_level_eq_kv(rest: str) -> dict | None:
    fields = _extract_kv(rest)
    if "level" not in fields:
        return None
    return fields


def _parse_structured_json(rest: str) -> dict | None:
    try:
        obj = json.loads(rest)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_syslog(rest: str) -> dict | None:
    m = re.match(r"^<\d+>\d+\s+\S+\s+\S+\s+\S+\s+-\s+-\s+(.*)$", rest)
    if not m:
        return None
    fields = _extract_kv(m.group(1))
    if "level" not in fields:
        return None
    return fields


_FAMILY_PARSERS = {
    "application_trace": _parse_application_trace,
    "cloud_runtime_export": _parse_cloud_runtime_export,
    "notification_delivery": _parse_bare_level_kv,
    "operations_stream": _parse_operations_stream,
    "resource_lookup_trace": _parse_level_eq_kv,
    "search_index_diagnostic": _parse_bare_level_kv,
    "service_events": _parse_level_eq_kv,
    "structured_service_events": _parse_structured_json,
    "support_replica": _parse_level_eq_kv,
    "syslog_archive": _parse_syslog,
}

_NEGATIVE_RESULTS = {"miss", "NOT_FOUND", "not_found"}
_POSITIVE_RESULTS = {"hit", "FOUND", "found"}


def _infer_exists(fields: dict) -> bool | None:
    rows = fields.get("rows")
    if rows is not None:
        return str(rows) != "0"
    result = fields.get("result")
    if result in _POSITIVE_RESULTS:
        return True
    if result in _NEGATIVE_RESULTS:
        return False
    http_status = fields.get("http_status")
    if http_status is not None:
        return str(http_status) == "200"
    return True  # resource_id present with no negative indicator: presence implies existence


_IDENTIFIER_LIKE_KEYS = {
    "lookup_key",
    "correlation_key",
    "match_key",
    "subject_reference",
    "subject_ref",
    "customer_email",
    "requester_email",
    "email",
}
_EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _fields_to_observation(
    fields: dict, event_time: datetime, source_id: str, manifest_time: datetime
) -> Observation | None:
    resource_id = fields.get("resource_id")
    if not resource_id:
        return None

    identifiers: set[str] = set()
    link_keys: set[str] = {resource_id}
    attrs: dict = {}
    for key, value in fields.items():
        if key in ("resource_id",):
            continue
        if key in _IDENTIFIER_LIKE_KEYS or (isinstance(value, str) and _EMAIL_SHAPE_RE.match(value)):
            identifiers.add("email")
            link_keys.add(value.strip().lower())
            continue
        attrs[key] = value

    entry = mapping.mapping_for_resource_id(resource_id)
    system_id = entry.system_id if entry else "unknown"
    category = fields.get("record_type") or (entry.data_category if entry else None)
    if category in ("SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"):
        # Grounded in the real event vocabulary (profiled across all 26 logs):
        # attachment_pii_scan / attachment_scan_started / thumbnail_failed
        # vs. message_pii_scan / message_scan_started.
        event_name = str(fields.get("event", ""))
        if "attachment" in event_name or "thumbnail" in event_name:
            category = "SUPPORT_ATTACHMENT"
        elif "message" in event_name:
            category = "SUPPORT_MESSAGE"

    return Observation(
        system_id=system_id,
        resource_id=resource_id,
        category=category,
        store=fields.get("service") or system_id,
        source_id=source_id,
        manifest_time=manifest_time,
        observed_at=event_time,
        exists=_infer_exists(fields),
        identifiers_present=frozenset(identifiers),
        attrs=attrs,
        link_keys=frozenset(link_keys),
    )


def parse_log_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], int]:
    """Returns (observations, unparsed_line_count)."""
    family = family_for_filename(Path(ev.file_path).name)
    parser = _FAMILY_PARSERS.get(family)
    observations: list[Observation] = []
    unparsed = 0

    for line in resolved_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = _TIMESTAMP_RE.match(line)
        if not m or parser is None:
            unparsed += 1
            continue
        ts_text, rest = m.groups()
        fields = parser(rest)
        if fields is None:
            unparsed += 1
            continue
        event_time = _parse_ts(ts_text)
        obs = _fields_to_observation(fields, event_time, ev.file_id, ev.captured_at)
        if obs is not None:
            observations.append(obs)

    return observations, unparsed
