"""The Digest contract, in a form an endpoint can enforce.

Prompt wording alone cannot stop a model wrapping its JSON in prose; a schema
can, which removes a whole class of parse failures. This mirrors the example in
prompt.txt — change one and change the other.
"""

REQUIRED_DIGEST_FIELDS = {"translated_title", "tldr", "topics"}

_ENTRY_LIST_SCHEMA = {"type": "array", "items": {"type": "string"}}

DIGEST_JSON_SCHEMA = {
    "name": "digest",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["translated_title", "tldr", "topics"],
        "properties": {
            "translated_title": {"type": "string"},
            "tldr": {"type": "string"},
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["heading", "actions", "bring", "notes"],
                    "properties": {
                        "heading": {"type": "string"},
                        "actions": _ENTRY_LIST_SCHEMA,
                        "bring": _ENTRY_LIST_SCHEMA,
                        "notes": _ENTRY_LIST_SCHEMA,
                    },
                },
            },
        },
    },
}
