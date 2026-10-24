"""Parser for the one plain-text evidence record (F04): the shift
handover, `evidence/records/customer_account_handover_*.txt`.

Format: a `Snapshot: <ISO timestamp>` header line, then zero or more
`- <ISO timestamp> | <system_id> | <resource_id> | <CATEGORY> | <STATE> |
<note>` lines. STATE vocabulary observed: FOUND, NOT_FOUND, IDENTIFIABLE,
ANONYMIZED, REDACTED, ACTIVE, BLOCKED, DISABLED. <note> is either an
email address, a bare user_NN reference, or the literal "no direct
identifier".
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit.loaders import EvidenceFile
    from audit.models import Observation
else:
    from ..loaders import EvidenceFile
    from ..models import Observation

_SNAPSHOT_RE = re.compile(r"^Snapshot:\s*(\S+)\s*$")
_ROW_RE = re.compile(
    r"^-\s*(\S+)\s*\|\s*([a-z_]+)\s*\|\s*([a-z_0-9]+)\s*\|\s*([A-Z_]+)\s*\|\s*([A-Z_]+)\s*\|\s*(.+)$"
)
_EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USER_REF_RE = re.compile(r"^user_\d+$")


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def parse_text_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], str | None]:
    """Returns (observations, snapshot_header_timestamp_or_None)."""
    text = resolved_path.read_text(encoding="utf-8")
    snapshot_ts = None
    observations: list[Observation] = []

    for line in text.splitlines():
        m = _SNAPSHOT_RE.match(line.strip())
        if m:
            snapshot_ts = m.group(1)
            continue

        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        ts_text, system_id, resource_id, category, state, note = m.groups()
        observed_at = _parse_ts(ts_text)
        note = note.strip()

        identifiers: set[str] = set()
        link_keys = {resource_id}
        if _EMAIL_SHAPE_RE.match(note):
            identifiers.add("email")
            link_keys.add(note.strip().lower())
        elif _USER_REF_RE.match(note):
            link_keys.add(note)

        attrs = {"state": state}
        if category == "BACKUP_ARCHIVE":
            attrs["restore_allowed"] = state == "ACTIVE"
        elif category in ("DATA_FLOW", "ACTIVE_DATA_FLOW"):
            attrs["enabled"] = state == "ACTIVE"

        observations.append(
            Observation(
                system_id=system_id,
                resource_id=resource_id,
                category=category,
                store="customer_account_handover",
                source_id=ev.file_id,
                manifest_time=ev.captured_at,
                observed_at=observed_at,
                exists=state != "NOT_FOUND",
                identifiers_present=frozenset(identifiers),
                attrs=attrs,
                link_keys=frozenset(link_keys),
            )
        )

    return observations, snapshot_ts
