"""Parser for the 4 .pdf evidence documents (F04), text-layer only
(PyMuPDF; all 4 have a usable text layer, confirmed in Phase 1).

Two of the four have a regular enough structure to parse into
Observations:
- legal_retention_register_*.pdf: a repeating
  `ORD-XXXX | user_NN | <type> | <date> | <amount> | Retain until <date>
  | <initials>` row per disputed order.
- security_retention_extract.pdf: a labeled "Record" block with
  "Event reference <audit_record_id>", "subject reference <user_id>",
  "event ...", "retain until ...".

The other two (account_history_report_*.pdf, delivery_correction_
attachment.pdf) are free-text customer statements with no repeating
delimiter structure; per the Phase 2 instructions they are not force-
parsed here. Their text and a shape description are returned so the
report can show them and a human decides how to use them.
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

_LEGAL_ROW_RE = re.compile(
    r"^(ORD-\d+)\s*\|\s*(user_\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*"
    r"Retain until\s*([^|]+?)\s*\|\s*(\S+)\s*$"
)


def _extract_text(resolved_path: Path) -> tuple[str, int]:
    import pymupdf as fitz

    doc = fitz.open(resolved_path)
    text = "".join(page.get_text() for page in doc)
    pages = doc.page_count
    doc.close()
    return text, pages


def _parse_legal_retention_register(lines: list[str], ev: EvidenceFile) -> list[Observation]:
    observations = []
    for line in lines:
        m = _LEGAL_ROW_RE.match(line.strip())
        if not m:
            continue
        order_ref, user_id, dispute_type, date_text, amount, retain_until, initials = m.groups()
        observations.append(
            Observation(
                system_id="legal_service",
                resource_id=order_ref,
                category="LEGAL_HOLD_RECORD",
                store="legal_retention_register",
                source_id=ev.file_id,
                manifest_time=ev.captured_at,
                observed_at=ev.captured_at,
                exists=True,
                identifiers_present=frozenset(),
                attrs={
                    "dispute_type": dispute_type.strip(),
                    "order_date": date_text.strip(),
                    "amount": amount.strip(),
                    "retain_until": retain_until.strip(),
                    "reviewer_initials": initials.strip(),
                },
                link_keys=frozenset({order_ref, user_id}),
            )
        )
    return observations


def _parse_security_retention_extract(lines: list[str], ev: EvidenceFile) -> list[Observation]:
    observations = []
    i = 0
    while i < len(lines):
        m = re.match(r"^Event reference\s+(\S+)\s*$", lines[i].strip())
        if not m:
            i += 1
            continue
        resource_id = m.group(1)
        block = {}
        j = i + 1
        while j < len(lines) and lines[j].strip() != "Record":
            line = lines[j].strip()
            sm = re.match(r"^subject reference\s+(\S+)\s*$", line)
            em = re.match(r"^event\s+(.+)$", line)
            am = re.match(r"^actor\s+(.+)$", line)
            rm = re.match(r"^recorded\s+(.+)$", line)
            tm = re.match(r"^retain until\s+(.+)$", line)
            if sm:
                block["subject_reference"] = sm.group(1)
            elif em:
                block["event"] = em.group(1)
            elif am:
                block["actor"] = am.group(1)
            elif rm:
                recorded = rm.group(1)
                if j + 1 < len(lines) and re.match(r"^\d{2}\s+UTC$", lines[j + 1].strip()):
                    recorded = f"{recorded} {lines[j + 1].strip()}"
                    j += 1
                block["recorded_at"] = recorded
            elif tm:
                retain = tm.group(1)
                if j + 1 < len(lines) and re.match(r"^\d{2}\s+UTC$", lines[j + 1].strip()):
                    retain = f"{retain} {lines[j + 1].strip()}"
                    j += 1
                block["retain_until"] = retain
            j += 1

        link_keys = {resource_id}
        if "subject_reference" in block:
            link_keys.add(block["subject_reference"])
        observations.append(
            Observation(
                system_id="security_service",
                resource_id=resource_id,
                category="SECURITY_AUDIT_LOG",
                store="security_retention_extract",
                source_id=ev.file_id,
                manifest_time=ev.captured_at,
                observed_at=ev.captured_at,
                exists=True,
                identifiers_present=frozenset(),
                attrs=block,
                link_keys=frozenset(link_keys),
            )
        )
        i = j

    return observations


_REGULAR_PARSERS = {
    "legal_retention_register": _parse_legal_retention_register,
    "security_retention_extract": _parse_security_retention_extract,
}


def parse_pdf_file(ev: EvidenceFile, resolved_path: Path) -> tuple[list[Observation], dict]:
    """Returns (observations, report_info). report_info always has
    'pages', 'text_chars', 'regular' (bool); when not regular it also
    has 'text' (the full extracted text, for a human to review)."""
    text, pages = _extract_text(resolved_path)
    lines = text.splitlines()
    stem = Path(ev.file_path).stem

    for prefix, parser in _REGULAR_PARSERS.items():
        if stem.startswith(prefix):
            observations = parser(lines, ev)
            return observations, {"pages": pages, "text_chars": len(text), "regular": True, "shape": prefix}

    return [], {"pages": pages, "text_chars": len(text), "regular": False, "text": text}
