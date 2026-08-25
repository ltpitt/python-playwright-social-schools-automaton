"""Reading Dutch dates and likely obligations out of raw Article text.

Two jobs that both come down to knowing Dutch calendar words: the pre-scan
hints handed to the model, and the post's own date, which Social Schools renders
as prose ("7 juli om 13:19", "afgelopen dinsdag om 15:39") rather than as a
machine-readable <time> element.

The hints are a heuristic pre-pass, not a substitute for the model's judgment —
they point it at likely dates and instructions instead of relying on it to
notice them unaided.
"""
import re
from datetime import date, timedelta

DATE_HINT_RE = re.compile(
    r'\b\d{1,2}\s*(?:jan|feb|mrt|maart|apr|mei|jun(?:i)?|jul(?:i)?|aug|sep|okt|nov|dec)[a-z]*\.?',
    re.IGNORECASE,
)
TIME_HINT_RE = re.compile(r'\b([01]?\d|2[0-3])[:.][0-5]\d\b')
IMPERATIVE_HINT_RE = re.compile(
    r'\b(graag|gelieve|zorg dat|vergeet niet|lever .{0,20}in|meenemen|inleveren|aanmeld\w*|betaal\w*|onderteken\w*)',
    re.IGNORECASE,
)

DUTCH_MONTHS = {
    "januari": "Jan", "februari": "Feb", "maart": "Mar", "april": "Apr",
    "mei": "May", "juni": "Jun", "juli": "Jul", "augustus": "Aug",
    "september": "Sep", "oktober": "Oct", "november": "Nov", "december": "Dec",
}
POST_DATETIME_RE = re.compile(
    r'(\d{1,2})\s+(' + "|".join(DUTCH_MONTHS) + r')\b(?:[^\d]{0,6}(\d{1,2}:\d{2}))?',
    re.IGNORECASE,
)

# Recent posts are labelled relatively and only older ones carry a month name,
# so relative labels must be resolved against the current date.
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
RELATIVE_DAY_OFFSETS = {"vandaag": 0, "gisteren": 1, "eergisteren": 2}
RELATIVE_DAY_RE = re.compile(
    r'\b(' + "|".join(RELATIVE_DAY_OFFSETS) + r')\b', re.IGNORECASE)
DUTCH_WEEKDAYS = {
    "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3,
    "vrijdag": 4, "zaterdag": 5, "zondag": 6,
}
WEEKDAY_RE = re.compile(r'\b(' + "|".join(DUTCH_WEEKDAYS) + r')\b', re.IGNORECASE)
TIME_OF_DAY_RE = re.compile(r'\b(\d{1,2}:\d{2})\b')


def extract_action_hints(text):
    """Candidate dates, times and imperative phrases found in raw text."""
    hints = []
    for match in DATE_HINT_RE.finditer(text):
        hints.append(f"date: {match.group(0).strip()}")
    for match in TIME_HINT_RE.finditer(text):
        hints.append(f"time: {match.group(0)}")
    for match in IMPERATIVE_HINT_RE.finditer(text):
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 40)
        snippet = " ".join(text[start:end].split())
        hints.append(f"instruction: \u2026{snippet}\u2026")
    return hints


def resolve_relative_dutch_date(text, today):
    """Resolve 'vandaag' / 'gisteren' / '(afgelopen) dinsdag' to a date, or None."""
    relative = RELATIVE_DAY_RE.search(text)
    if relative:
        return today - timedelta(days=RELATIVE_DAY_OFFSETS[relative.group(1).lower()])

    weekday = WEEKDAY_RE.search(text)
    if weekday:
        # Social Schools only labels days this way when they are in the recent past.
        days_back = (today.weekday() - DUTCH_WEEKDAYS[weekday.group(1).lower()]) % 7 or 7
        return today - timedelta(days=days_back)

    return None


def parse_post_datetime(posted, today=None):
    """Turn one Dutch date label into 'D Mon' or 'D Mon HH:MM', or None."""
    match = POST_DATETIME_RE.search(posted)
    if match:
        day, month_nl, time_part = match.group(1), match.group(2).lower(), match.group(3)
        month_abbr = DUTCH_MONTHS.get(month_nl)
        if not month_abbr:
            return None
        result = f"{int(day)} {month_abbr}"
        if time_part:
            result += f" {time_part}"
        return result

    resolved = resolve_relative_dutch_date(posted, today or date.today())
    if not resolved:
        return None
    result = f"{resolved.day} {MONTH_ABBR[resolved.month - 1]}"
    time_match = TIME_OF_DAY_RE.search(posted)
    if time_match:
        result += f" {time_match.group(1)}"
    return result
