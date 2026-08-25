"""The nouns of the domain, as defined in CONTEXT.md.

Data only, no behaviour and no imports beyond the stdlib, so anything in the
project can name a Digest without dragging a provider or a browser along.
"""
from dataclasses import dataclass, field


@dataclass
class Attachment:
    """A PDF or Word document linked from an Article."""
    filename: str
    url: str
    filetype: str   # "pdf" or "docx"
    text: str
    failed: bool = False


@dataclass
class Topic:
    """One subject within a message, mirroring how the school actually organised it."""
    heading: str
    actions: list = field(default_factory=list)
    bring: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class Digest:
    """The parent-facing brief produced for one Article, in the reader's language."""
    translated_title: str
    tldr: str
    topics: list = field(default_factory=list)


@dataclass
class Recipient:
    """Someone who gets notified, and the language they want it in."""
    value: str  # Pushbullet token or email address
    language: str
