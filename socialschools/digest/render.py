"""Laying a Digest out as the text a parent actually reads on their phone."""
import re

from ..models import Digest

# The model is told to date every entry it can, which is right for correctness
# but reads badly when a whole topic is one day: '01 Sep -' down every line.
# Lifting the shared date into the heading is a rendering job, not a prompt one.
ENTRY_DATE_PREFIX_RE = re.compile(r'^(\d{1,2}\s+[A-Za-z]{3})\s*-\s*')
MIN_ENTRIES_TO_LIFT_DATE = 2

# A message this long is a newsletter, and a brief of one is always a selection.
# Saying so is the honest part: without it a parent cannot tell the difference
# between "nothing else happened" and "forty items did not fit".
ABRIDGE_SOURCE_CHARS = 4000
ABRIDGED_NOTE = "\u2139 Summary of a long newsletter \u2014 open the post for the full list"


def shared_entry_date(entries):
    """The one date every dated entry carries, or None if they differ or are too few."""
    dates = [match.group(1) for match in
             (ENTRY_DATE_PREFIX_RE.match(entry) for entry in entries) if match]
    if len(dates) >= MIN_ENTRIES_TO_LIFT_DATE and len(set(dates)) == 1:
        return dates[0]
    return None


def without_date_prefix(entry, shared_date):
    match = ENTRY_DATE_PREFIX_RE.match(entry)
    return entry[match.end():] if match and match.group(1) == shared_date else entry


def render_topic(topic):
    """One topic as its own block: heading, actions, a single bring line, then notes."""
    lines = []
    shared_date = shared_entry_date(topic.actions + topic.notes)
    heading = topic.heading
    if shared_date:
        heading = f"{shared_date} \u00b7 {heading}" if heading else shared_date
    if heading:
        lines.append(f"\u2501 {heading}")
    lines.extend(f"\u25b8 {without_date_prefix(action, shared_date)}"
                 for action in topic.actions)
    if topic.bring:
        lines.append("\U0001F392 Bring: " + ", ".join(topic.bring))
    lines.extend(f"\u00b7 {without_date_prefix(note, shared_date)}"
                 for note in topic.notes)
    return "\n".join(lines)


def render_digest_notification(data: Digest, failed_attachments=None,
                               original_title=None, post_date=None, abridged=False):
    sections = []

    if post_date:
        sections.append(f"\U0001F4C5 {post_date}")

    tldr = data.tldr.strip()
    if tldr:
        sections.append(tldr)

    sections.extend(render_topic(topic) for topic in data.topics)

    if not any(topic.actions or topic.bring for topic in data.topics):
        sections.append("No action needed")

    if abridged:
        sections.append(ABRIDGED_NOTE)

    if failed_attachments:
        sections.append(
            "\u26a0 An attachment could not be read \u2014 check the original post for complete info")

    if original_title:
        sections.append(f"To find this post in Social Schools, look for: \"{original_title}\"")

    return "\n\n".join(sections)
