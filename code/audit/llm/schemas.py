"""Strict JSON schemas for every model output (Phase 4 C3: invalid
output is rejected, never repaired by guessing). Validated in
code/audit/llm/client.py with `jsonschema` after every call, cached or
live, before the result is trusted by anything else.
"""

INTENT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["DELETE", "NOT_DELETE", "UNCLEAR"]},
        "language": {"type": "string", "minLength": 2, "maxLength": 8},
        "evidence_phrase": {"type": "string", "minLength": 1},
    },
    "required": ["intent", "language", "evidence_phrase"],
    "additionalProperties": False,
}

INTENT_BATCH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "intent": {"type": "string", "enum": ["DELETE", "NOT_DELETE", "UNCLEAR"]},
                    "language": {"type": "string", "minLength": 2, "maxLength": 8},
                    "evidence_phrase": {"type": "string"},
                },
                "required": ["id", "intent", "language", "evidence_phrase"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}

# Built at import time from mapping.py (document type and system-name
# enums are data-driven, never hardcoded ahead of what the mapping
# table actually defines) -- see vision_schema() below.
_IDENTIFIER_KINDS = ["email", "phone", "hash", "name"]


def vision_schema(system_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": [
                    "account_statement",
                    "support_record",
                    "console_screenshot",
                    "object_storage_browser",
                    "other",
                ],
            },
            "system_id": {"type": "string", "enum": sorted(set(system_ids) | {"unknown"})},
            "resource_ids": {"type": "array", "items": {"type": "string"}},
            "identifiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": _IDENTIFIER_KINDS},
                        "value": {"type": "string"},
                    },
                    "required": ["kind", "value"],
                    "additionalProperties": False,
                },
            },
            "observed_state_words": {"type": "array", "items": {"type": "string"}},
            "timestamps": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "document_type",
            "system_id",
            "resource_ids",
            "identifiers",
            "observed_state_words",
            "timestamps",
        ],
        "additionalProperties": False,
    }
