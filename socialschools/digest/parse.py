"""Getting a typed Digest out of whatever the model actually returned.

Two separable problems. Finding the JSON is a tolerance problem: a model asked
for JSON may still wrap it in prose or a markdown fence. Validating it is a
semantics problem: the shape can be perfect and the content still empty, and an
empty brief delivered to a parent is worse than a retry.
"""
import json
import re

from ..models import Digest, Topic
from .schema import REQUIRED_DIGEST_FIELDS


def extract_json(text):
    """The first valid JSON object in a response, however it was wrapped."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Scan forward with raw_decode rather than regex: a greedy pattern fails on
    # JSON that contains braces, which the Digest example does.
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find('{', idx)
        if start == -1:
            break
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            idx = start + 1
    raise ValueError("No valid JSON found in response")


def clean_entry_list(value, where):
    """Validate a topic's entry list and drop duplicates, preserving order."""
    if not isinstance(value, list):
        raise ValueError(f"'{where}' must be a list")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"'{where}' must contain only non-empty strings")
    return list(dict.fromkeys(value))


def dict_to_digest(data: dict) -> Digest:
    """Validate a raw dict's semantics, not just its shape, and type it.

    Raises ValueError on missing or malformed fields, non-string list items, or
    a digest carrying no actual content, so callers can retry instead of
    silently delivering an empty brief.
    """
    missing = REQUIRED_DIGEST_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    if not isinstance(data.get("translated_title"), str) or not data["translated_title"].strip():
        raise ValueError("'translated_title' must be a non-empty string")
    if not isinstance(data.get("tldr"), str):
        raise ValueError("'tldr' must be a string")
    if not isinstance(data.get("topics"), list):
        raise ValueError("'topics' must be a list")

    topics = []
    for raw in data["topics"]:
        if not isinstance(raw, dict):
            raise ValueError("Each topic must be an object")
        heading = raw.get("heading", "")
        if not isinstance(heading, str):
            raise ValueError("'heading' must be a string")
        topic = Topic(
            heading=heading.strip(),
            actions=clean_entry_list(raw.get("actions", []), "actions"),
            bring=clean_entry_list(raw.get("bring", []), "bring"),
            notes=clean_entry_list(raw.get("notes", []), "notes"),
        )
        if topic.actions or topic.bring or topic.notes:
            topics.append(topic)

    if not data["tldr"].strip() and not topics:
        raise ValueError("Digest has no content: 'tldr' is empty and no topic carries any entry")

    return Digest(
        translated_title=data["translated_title"],
        tldr=data["tldr"],
        topics=topics,
    )
