"""Shared field classification for the SQL and JSON parsers.

Both formats embed the same kind of loosely-typed record: a flat or
one-level-nested dict of column/key names that vary by collection
(customer_profiles vs. support_records vs. a nested "document" inside a
customer_search_documents record, etc.). This module classifies a dict's
keys into identifiers (PII a deletion rule cares about), link keys
(references usable by the linker, never treated as PII themselves),
attrs (everything else, used by the policy engine later), and explicit
resource-to-resource references (Phase 3b: a `*_resource_id`-shaped
field, never the bare `resource_id` key itself, whose value also has a
recognized code/audit/mapping.py prefix shape -- e.g. the real
`search_documents_primary.source_resource_id` column pointing at an
`account_NNN`). References are kept OUT of link_keys on purpose: they
are not an identity value, and code/audit/linker.py's reference_closure
rule must never treat a reference the same way it treats a shared
email/phone/hash/user_id.
"""

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from audit import mapping
else:
    from .. import mapping

REFERENCE_KEYS = {"customer_reference", "subject_reference", "user_id", "resource_id"}
EMAIL_HASH_SUBSTR = "email_hash"
EMAIL_SUBSTR = "email"
PHONE_SUBSTR = "phone"
NAME_KEYS = {"full_name", "display_name", "requester_name", "name"}

EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def classify_record(data: dict) -> tuple[set[str], set[str], dict, set[str]]:
    """Walk a (possibly one-level-nested) dict and classify its fields.

    Returns (identifiers_present, link_key_values, attrs, references).
    `attrs` holds every scalar field that is not an identifier, a
    reference key, or an explicit resource reference, flattened by leaf
    key name. Lists are summarized by length only.
    """
    identifiers: set[str] = set()
    link_keys: set[str] = set()
    attrs: dict = {}
    references: set[str] = set()

    def visit(d: dict):
        for key, value in d.items():
            if value is None:
                continue
            lower_key = key.lower()
            if isinstance(value, dict):
                visit(value)
                continue
            if isinstance(value, list):
                attrs[f"{key}_count"] = len(value)
                continue
            if lower_key.endswith("_resource_id") and lower_key != "resource_id":
                # A directed pointer to ANOTHER record (e.g.
                # source_resource_id), never this record's own id and
                # never an identity value -- only accepted into
                # `references` (not link_keys) when its value actually
                # has a known resource-id prefix shape, so a decoy or
                # malformed value can never become a bridge.
                if mapping.prefix_for_resource_id(str(value)):
                    references.add(str(value))
                continue
            if key in REFERENCE_KEYS or lower_key.endswith("_reference"):
                link_keys.add(str(value))
                continue
            if EMAIL_HASH_SUBSTR in lower_key:
                identifiers.add("email_hash")
                link_keys.add(str(value).strip().lower())
                continue
            if EMAIL_SUBSTR in lower_key:
                identifiers.add("email")
                link_keys.add(str(value).strip().lower())
                continue
            if PHONE_SUBSTR in lower_key:
                identifiers.add("phone")
                link_keys.add(str(value))
                continue
            if key in NAME_KEYS:
                identifiers.add("name")
                attrs[key] = value
                continue
            if isinstance(value, str) and EMAIL_SHAPE_RE.match(value):
                # A value that looks like an email under an unrecognized key
                # (e.g. a log's correlation_key) is still an identifier.
                identifiers.add("email")
                link_keys.add(value.strip().lower())
                continue
            attrs[key] = value

    visit(data)
    return identifiers, link_keys, attrs, references
