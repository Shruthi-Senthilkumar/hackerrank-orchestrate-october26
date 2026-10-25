"""F05 image reading (Phase 4): OCR grounding + two Gemini readers.

For one image: OCR first (cached, local, free -- the independent
grounding source, never a decision-maker on its own). Then the
primary Gemini reader (gemini-3.1-flash-lite) extracts structured
facts with a strict schema. Then the second reader (gemini-3.8-flash,
budgeted) reads the SAME image. Every extracted identifier/resource id
from EITHER reader must appear in the OCR text (after normalization)
or it is dropped and counted (C5 grounding). Of what survives
grounding, only fields on which BOTH readers agree are kept;
disagreeing fields are dropped and counted. If a reader is
unavailable (budget exhausted, AIDisabledError in --no-ai mode, or two
failed attempts), the file falls back to OCR-only grounded facts and
is flagged -- never guessed at.

Agreed facts become Observations through the same normalization used
by every other parser (resource_id -> category/system_id via
mapping.py, link_keys from identifiers), so they flow through the SAME
linker rules as everything else (identity_key, same_document via a
DocumentHint keyed by this image's own file_id -- an image has no
trace_id, so trace_correlation never applies to it).
"""

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from audit import mapping  # noqa: E402
from audit.llm import client, replay  # noqa: E402
from audit.models import DocumentHint, Observation  # noqa: E402
from audit.security import sanitize  # noqa: E402
import config  # noqa: E402

# ocr_adapter (and its onnxruntime import) is loaded lazily, only when
# a replay entry is NOT already available -- the keyless replay path
# must never import onnxruntime at all (final-phase task 1).

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "vision_v1.md"

_WS_RE = re.compile(r"\s+")


def _load_vision_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _normalize_for_grounding(s: str) -> str:
    return _WS_RE.sub("", s).lower()


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def is_grounded(value: str, ocr_text_value: str, kind: str = "") -> bool:
    """A value is grounded if it appears in the OCR text after
    normalization. Phone numbers also get a digits-only comparison,
    since OCR and the model frequently disagree on spacing/punctuation
    that carries no real information."""
    if not value:
        return False
    norm_value = _normalize_for_grounding(value)
    norm_ocr = _normalize_for_grounding(ocr_text_value)
    if norm_value and norm_value in norm_ocr:
        return True
    if kind == "phone":
        d_value, d_ocr = _digits_only(value), _digits_only(ocr_text_value)
        if d_value and d_value in d_ocr:
            return True
    return False


@dataclass
class ImageReadReport:
    file_id: str
    document_type: str
    system_id: str
    facts_extracted: int
    facts_grounded: int
    facts_dropped: int
    disagreements: int
    second_reader_used: bool
    second_reader_available: bool
    flagged: str  # reason, or "" if not flagged
    agreed: dict = field(default_factory=dict)


def _read_one(image_bytes: bytes, mime_type: str, model: str, system_ids: list[str], ai_enabled: bool, prompt: str) -> Optional[dict]:
    try:
        return client.extract_image_facts(image_bytes, mime_type, model, system_ids, ai_enabled, prompt)
    except Exception:
        try:
            return client.extract_image_facts(image_bytes, mime_type, model, system_ids, ai_enabled, prompt)
        except Exception:
            return None


def _agree_scalar(a, b):
    return a if a == b else None


def _agree_list_of_strings(a: list, b: list) -> list:
    return [x for x in a if x in b]


def _agree_identifiers(a: list, b: list) -> list:
    b_pairs = {(i["kind"], i["value"]) for i in b}
    return [i for i in a if (i["kind"], i["value"]) in b_pairs]


def read_image(
    file_id: str,
    image_bytes: bytes,
    mime_type: str,
    ai_enabled: bool,
) -> tuple[Optional[dict], ImageReadReport]:
    """Returns (agreed_facts_or_none, report). agreed_facts is None
    only if nothing at all survived (every field dropped)."""
    replayed = replay.get_image(image_bytes)
    if replayed is not None:
        r = replayed["report"]
        return replayed["agreed"], ImageReadReport(
            file_id=file_id, document_type=r["document_type"], system_id=r["system_id"],
            facts_extracted=r["facts_extracted"], facts_grounded=r["facts_grounded"],
            facts_dropped=r["facts_dropped"], disagreements=r["disagreements"],
            second_reader_used=r["second_reader_used"], second_reader_available=r["second_reader_available"],
            flagged=r["flagged"], agreed=replayed["agreed"],
        )

    system_ids = mapping.all_system_ids()
    prompt = _load_vision_prompt()
    from audit.evidence.ocr_adapter import ocr_text  # lazy: only reached on a replay miss

    raw_ocr = ocr_text(image_bytes)
    masked_ocr, _flags = sanitize.sanitize(raw_ocr)  # OCR text can carry injected text too

    primary = _read_one(image_bytes, mime_type, config.EXTRACT_MODEL, system_ids, ai_enabled, prompt)

    second_available = True
    second = None
    if primary is not None:
        second = _read_one(image_bytes, mime_type, config.EXTRACT_MODEL_RARE, system_ids, ai_enabled, prompt)
        if second is None:
            second_available = False

    extracted = 0
    dropped = 0
    disagreements = 0
    flagged = ""

    if primary is None:
        flagged = "primary reader unavailable after two attempts"
        return None, ImageReadReport(
            file_id=file_id, document_type="", system_id="unknown", facts_extracted=0, facts_grounded=0,
            facts_dropped=0, disagreements=0, second_reader_used=False, second_reader_available=False, flagged=flagged,
        )

    def ground_list(items, kind_fn=lambda x: ""):
        nonlocal extracted, dropped
        kept = []
        for item in items:
            extracted += 1
            value = item if isinstance(item, str) else item.get("value", "")
            kind = kind_fn(item)
            if is_grounded(value, raw_ocr, kind):
                kept.append(item)
            else:
                dropped += 1
        return kept

    def ground_resource_ids(items):
        """Grounding alone is not enough for resource_ids: the model's
        schema has no enum for them (resource ids vary too much to
        enumerate), so a UI label that is genuinely visible on the
        image (e.g. "Delivery tracking", a menu entry) can pass the
        grounding check while never being a real resource id at all.
        Require it to also match a known mapping.py prefix shape --
        the same requirement code/audit/mapping.py's own
        find_resource_ids_in_text() already applies to PDF text."""
        nonlocal extracted, dropped
        kept = []
        for value in items:
            extracted += 1
            if is_grounded(value, raw_ocr) and mapping.prefix_for_resource_id(value):
                kept.append(value)
            else:
                dropped += 1
        return kept

    primary_grounded = {
        "document_type": primary["document_type"],
        "system_id": primary["system_id"],
        "resource_ids": ground_resource_ids(primary["resource_ids"]),
        "identifiers": ground_list(primary["identifiers"], lambda i: i.get("kind", "")),
        "observed_state_words": list(primary["observed_state_words"]),
        "timestamps": list(primary["timestamps"]),
    }
    extracted += 2  # document_type, system_id counted as single facts

    if second is None:
        agreed = primary_grounded
        flagged = "second reader unavailable; using primary (grounded) only" if not second_available else ""
    else:
        second_grounded = {
            "document_type": second["document_type"],
            "system_id": second["system_id"],
            "resource_ids": ground_resource_ids(second["resource_ids"]),
            "identifiers": ground_list(second["identifiers"], lambda i: i.get("kind", "")),
            "observed_state_words": list(second["observed_state_words"]),
            "timestamps": list(second["timestamps"]),
        }

        agreed_doc_type = _agree_scalar(primary_grounded["document_type"], second_grounded["document_type"])
        agreed_system_id = _agree_scalar(primary_grounded["system_id"], second_grounded["system_id"])
        agreed_resource_ids = _agree_list_of_strings(primary_grounded["resource_ids"], second_grounded["resource_ids"])
        agreed_identifiers = _agree_identifiers(primary_grounded["identifiers"], second_grounded["identifiers"])
        agreed_state_words = _agree_list_of_strings(primary_grounded["observed_state_words"], second_grounded["observed_state_words"])
        agreed_timestamps = _agree_list_of_strings(primary_grounded["timestamps"], second_grounded["timestamps"])

        disagreements += int(agreed_doc_type is None)
        disagreements += int(agreed_system_id is None)
        disagreements += len(primary_grounded["resource_ids"]) - len(agreed_resource_ids)
        disagreements += len(primary_grounded["identifiers"]) - len(agreed_identifiers)
        disagreements += len(primary_grounded["observed_state_words"]) - len(agreed_state_words)
        disagreements += len(primary_grounded["timestamps"]) - len(agreed_timestamps)

        agreed = {
            "document_type": agreed_doc_type or primary_grounded["document_type"],
            "system_id": agreed_system_id or "unknown",
            "resource_ids": agreed_resource_ids,
            "identifiers": agreed_identifiers,
            "observed_state_words": agreed_state_words,
            "timestamps": agreed_timestamps,
        }

    report = ImageReadReport(
        file_id=file_id,
        document_type=agreed.get("document_type", ""),
        system_id=agreed.get("system_id", "unknown"),
        facts_extracted=extracted,
        facts_grounded=extracted - dropped,
        facts_dropped=dropped,
        disagreements=disagreements,
        second_reader_used=second is not None,
        second_reader_available=second_available,
        flagged=flagged,
        agreed=agreed,
    )
    return agreed, report


_TIMESTAMP_FORMATS = ("%d %b %Y %H:%M", "%d %b %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def _parse_best_timestamp(timestamps: list[str], manifest_time: datetime) -> datetime:
    """Best-effort recency timestamp from the image's own visible
    text (D15: never gates visibility, only recency among already-
    visible facts). A timezone abbreviation (e.g. "JST") is stripped
    first since strptime cannot reliably parse arbitrary ones; the
    date/time itself is still used, assumed UTC. Any timestamp that
    does not parse is silently skipped -- falling back to
    manifest_time is always safe, just less precise."""
    parsed = []
    for raw in timestamps:
        text = re.sub(r"\s+[A-Z]{2,4}$", "", raw.strip())
        for fmt in _TIMESTAMP_FORMATS:
            try:
                parsed.append(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
    return max(parsed) if parsed else manifest_time


def facts_to_observations(
    file_id: str, agreed: dict, manifest_time: datetime, resource_timestamp: Optional[datetime] = None
) -> tuple[list[Observation], list[DocumentHint]]:
    """Converts one image's agreed facts into Observations + a
    DocumentHint per identifier, exactly like the PDF same_document
    mechanism (code/audit/evidence/pdf_parser.py), so an image's
    identifier-bearing facts can link an image resource_id to a person
    without ever guessing from an ID-number pattern."""
    observations: list[Observation] = []
    hints: list[DocumentHint] = []
    observed_at = resource_timestamp or _parse_best_timestamp(agreed.get("timestamps", []), manifest_time)

    # Identifiers flow ONLY through a DocumentHint, exactly like
    # code/audit/evidence/pdf_parser.py's same_document mechanism --
    # never baked directly into every resource's own link_keys. An
    # image can show more than one person's records (e.g. a search
    # result list); letting identifiers bypass the same_document rule's
    # own safety checks would risk the same cross-person contamination
    # already found and fixed for JSON/log evidence in Phase 3b. Never
    # add a name (identifiers with kind=="name") as a link key or hint
    # value -- a name alone never links.
    for ident in agreed.get("identifiers", []):
        if ident["kind"] == "name":
            continue
        value = ident["value"].strip()
        if ident["kind"] == "email":
            value = value.lower()
        hints.append(DocumentHint(document_id=file_id, value=value, event_time=observed_at, source_id=file_id))

    state_words = {w.lower() for w in agreed.get("observed_state_words", [])}
    exists = not any(w in state_words for w in ("deleted", "absent", "removed", "not found", "none"))

    for resource_id in agreed.get("resource_ids", []):
        entry = mapping.mapping_for_resource_id(resource_id)
        system_id = entry.system_id if entry else (agreed.get("system_id") or "unknown")
        category = entry.data_category if entry else None
        observations.append(
            Observation(
                system_id=system_id,
                resource_id=resource_id,
                category=category,
                store="image_extraction",
                source_id=file_id,
                manifest_time=manifest_time,
                observed_at=observed_at,
                exists=exists,
                identifiers_present=frozenset({i["kind"] for i in agreed.get("identifiers", [])}),
                attrs={"state_words": sorted(state_words)} if state_words else {},
                link_keys=frozenset({resource_id}),
            )
        )
    return observations, hints
