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
(Decided in Phase 2's open questions, confirmed in Phase 2b: a log
proves only the exact resource it names.)

Phase 2b addition: a line can carry an identifier of the person
(lookup_key, subject_ref/subject_key, correlation_key, or an email
under any key) without yet having a resolved resource_id (e.g. a
"profile_lookup_started" line), while a later line of the same
trace_id has the resource_id but no identifier of its own (the
matching "_completed" line). Every such identifier is collected into a
TraceHint, keyed by trace_id, regardless of whether its own line has a
resource_id. The only other trace-like key found in this dataset is
`requestId` (cloud_runtime_export family); profiling showed it is
unique per line there, never reused across lines the way trace_id is,
so it is not treated as a correlation key. `correlation_id` does not
appear anywhere in the data.
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
    from audit.models import Observation, TraceHint
else:
    from .. import mapping
    from ..loaders import EvidenceFile
    from ..models import Observation, TraceHint

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
    event_name = str(fields.get("event", ""))
    if event_name.endswith("_started"):
        # A "*_started" line (e.g. profile_lookup_started) has not
        # concluded anything yet -- it often shares the resource_id of
        # the later "*_completed" line that carries the real result, at
        # the same timestamp in some log families. Claiming presence
        # here would let a meaningless "started" marker outrank the
        # real result; report unknown instead so only the concluding
        # line's fact is used.
        return None
    return True  # resource_id present with no negative indicator: presence implies existence


_IDENTIFIER_LIKE_KEYS = {
    "lookup_key",
    "correlation_key",
    "match_key",
    "subject_reference",
    "subject_ref",
    "subject_key",
    "customer_email",
    "requester_email",
    "email",
}
_EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USER_ID_SHAPE_RE = re.compile(r"^user_\d+$")


def _identifier_values(fields: dict) -> list[tuple[str, str]]:
    """Every (kind, value) identifier found in a parsed line's fields.
    kind is 'email' or 'user_id'; used both for a resource-bearing
    line's own link_keys and for trace-hint extraction on lines with no
    resource_id of their own."""
    found = []
    for key, value in fields.items():
        if key == "resource_id" or not isinstance(value, str):
            continue
        if key in _IDENTIFIER_LIKE_KEYS or _EMAIL_SHAPE_RE.match(value):
            if _USER_ID_SHAPE_RE.match(value):
                found.append(("user_id", value))
            else:
                found.append(("email", value.strip().lower()))
    return found


def _fields_to_observation(
    fields: dict, event_time: datetime, source_id: str, manifest_time: datetime
) -> Observation | None:
    resource_id = fields.get("resource_id")
    if not resource_id:
        return None

    identifiers: set[str] = set()
    link_keys: set[str] = {resource_id}
    identifier_keys = {key for key, value in fields.items() if key in _IDENTIFIER_LIKE_KEYS}
    for kind, value in _identifier_values(fields):
        identifiers.add("email" if kind == "email" else "other")
        link_keys.add(value)
    attrs: dict = {}
    for key, value in fields.items():
        if key in ("resource_id",) or key in identifier_keys:
            continue
        if isinstance(value, str) and (_EMAIL_SHAPE_RE.match(value) or _USER_ID_SHAPE_RE.match(value)):
            continue  # already captured above via _identifier_values' value-shape match
        attrs[key] = value

    entry = mapping.mapping_for_resource_id(resource_id)
    system_id = entry.system_id if entry else "unknown"
    category = fields.get("record_type") or (entry.data_category if entry else None)
    if category in ("SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"):
        category = mapping.disambiguate_support_category(
            str(fields.get("event", "")), default=category, service=str(fields.get("service", ""))
        )
    if category == "ANALYTICS_PROFILE" and (
        "contact_lookup" in str(fields.get("event", "")) or "email_opt_in" in fields
    ):
        # A rare but distinct event shape (checked: appears exactly once
        # across all 26 logs) carries an email_opt_in preference under an
        # analytics_ prefixed resource_id/analytics_platform service --
        # a marketing opt-in record, not analytics behavior tracking.
        # MARKETING_PROFILE's required action (DELETE) matches the
        # sample; the default ANONYMIZE would not.
        category = "MARKETING_PROFILE"

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


def parse_log_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], int, list[TraceHint]]:
    """Returns (observations, unparsed_line_count, trace_hints).

    trace_hints are built from EVERY line that carries a trace_id and an
    identifier-like value, whether or not that line also has a
    resource_id of its own (a "profile_lookup_started" line has the
    identifier but not yet a resolved resource; the matching
    "_completed" line later in the same trace has the resource_id but
    often no identifier of its own -- see
    code/audit/linker.py's trace_correlation rule, which is the only
    consumer of these hints)."""
    family = family_for_filename(Path(ev.file_path).name)
    parser = _FAMILY_PARSERS.get(family)
    observations: list[Observation] = []
    trace_hints: list[TraceHint] = []
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

        trace_id = fields.get("trace_id")
        if trace_id:
            for _kind, value in _identifier_values(fields):
                trace_hints.append(TraceHint(trace_id=trace_id, value=value, event_time=event_time, source_id=ev.file_id))

        obs = _fields_to_observation(fields, event_time, ev.file_id, ev.captured_at)
        if obs is not None:
            observations.append(obs)

    return observations, unparsed, trace_hints
