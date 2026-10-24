"""Shared field classification for the SQL and JSON parsers.

Both formats embed the same kind of loosely-typed record: a flat or
one-level-nested dict of column/key names that vary by collection
(customer_profiles vs. support_records vs. a nested "document" inside a
customer_search_documents record, etc.). This module classifies a dict's
keys into identifiers (PII a deletion rule cares about), link keys
(references usable by the linker, never treated as PII themselves), and
attrs (everything else, used by the policy engine later).
"""

import re

REFERENCE_KEYS = {"customer_reference", "subject_reference", "user_id", "resource_id"}
EMAIL_HASH_SUBSTR = "email_hash"
EMAIL_SUBSTR = "email"
PHONE_SUBSTR = "phone"
NAME_KEYS = {"full_name", "display_name", "requester_name", "name"}

EMAIL_SHAPE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def classify_record(data: dict) -> tuple[set[str], set[str], dict]:
    """Walk a (possibly one-level-nested) dict and classify its fields.

    Returns (identifiers_present, link_key_values, attrs). `attrs` holds
    every scalar field that is not an identifier or a reference key,
    flattened by leaf key name. Lists are summarized by length only.
    """
    identifiers: set[str] = set()
    link_keys: set[str] = set()
    attrs: dict = {}

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
            if key in REFERENCE_KEYS or lower_key.endswith(("_reference", "_resource_id")):
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
    return identifiers, link_keys, attrs
