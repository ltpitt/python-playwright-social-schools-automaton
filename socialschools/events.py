"""Wide structured events — one per unit of work, written raw.

Every run and every Article produces exactly one event carrying everything known
about it by the time it finishes. Not a line per step: a line per *thing that
happened*, dense enough to answer questions nobody thought to ask when it was
written. That is the canonical-log-line idea, and the reason for it is that
aggregation is a one-way trip — a count of failures can never be turned back
into the reason for them, but raw events can always be counted.

`events.jsonl` is therefore the source of truth and `run_report.txt` is the
narration. The event says a digest lost its footer; the log says what the model
returned that time.

Events carry SHAPES, NEVER CONTENT. `title_sha8`, `body_chars`, `topics=2`,
`has_footer=true` — never a sentence from a post. The usual advice is to throw
everything into the blob, but the blob here would be children's names, and this
file is meant to survive for months. Correlate by run_id and read the debug log
when the text actually matters.

Stdlib only, and nothing here may import the application: an event must be
cheap enough that no call site hesitates to add one.
"""
import hashlib
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from . import paths

EVENTS_PATH = os.environ.get("EVENTS_PATH") or paths.EVENTS_FILE
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5

# One id per process, stamped on every event and every log line, so a canonical
# event and the narration behind it can always be brought back together.
RUN_ID = uuid.uuid4().hex[:8]

_logger = logging.getLogger("events")
# Deliberately not this module's __name__: that logger owns events.jsonl, and a
# human-readable line written to it would corrupt the machine-readable file.
_narration = logging.getLogger("canonical")


def _writer():
    if not _logger.handlers:
        handler = RotatingFileHandler(paths.ensure_parent(EVENTS_PATH), maxBytes=MAX_BYTES,
                                      backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
    return _logger


def sha8(text):
    """A stable handle for a string whose content must not be stored."""
    if text is None:
        return None
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:8]


def _run_git(*args):
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


_ENVIRONMENT = {}


def environment():
    """Which code, on which machine. Cached: it cannot change mid-run."""
    if not _ENVIRONMENT:
        dirty = _run_git("status", "--porcelain")
        _ENVIRONMENT.update({
            "commit": _run_git("rev-parse", "--short", "HEAD"),
            # The question 'is the box running what I think it is' has cost hours.
            "git_dirty": None if dirty is None else bool(dirty),
            "host": socket.gethostname(),
            "python": platform.python_version(),
            "platform": platform.system().lower(),
            "argv": " ".join(sys.argv[1:]),
        })
    return dict(_ENVIRONMENT)


def logfmt(record):
    """The same event as one human-scannable line."""
    parts = []
    for key, value in record.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, float):
            rendered = f"{value:.6g}"
        else:
            rendered = str(value)
        if any(character in rendered for character in ' ="'):
            rendered = '"' + rendered.replace('"', "'") + '"'
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def emit(record):
    """Write one event. Never raises: telemetry must not break the work it watches."""
    try:
        # default=str because a field is worth keeping even when it is some object
        # nobody anticipated; losing the whole event over one value would be worse.
        _writer().info(json.dumps(record, ensure_ascii=False, sort_keys=False, default=str))
    except Exception as exc:
        _narration.warning(f"Could not write canonical event: {exc}")
    return record


class Event:
    """A unit of work that reports on itself once, when it is over.

    Fields accumulate as the work proceeds; the event is written on exit whether
    the work succeeded, failed or raised. A unit of work that crashes is exactly
    the one you most want a record of, so emission lives in a finally.
    """

    def __init__(self, name, **fields):
        self.record = {
            "event": name,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": RUN_ID,
        }
        self.record.update(fields)
        self._started = None

    def __setitem__(self, key, value):
        self.record[key] = value

    def __getitem__(self, key):
        return self.record[key]

    def get(self, key, default=None):
        return self.record.get(key, default)

    def update(self, **fields):
        self.record.update(fields)
        return self

    def add(self, key, amount=1):
        """Accumulate a counter without the caller having to initialise it."""
        self.record[key] = self.record.get(key, 0) + amount
        return self

    def __enter__(self):
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.record["duration_ms"] = round((time.monotonic() - self._started) * 1000, 1)
        if exc is not None:
            self.record["outcome"] = "error"
            self.record["error_type"] = exc_type.__name__
            self.record["error"] = str(exc)[:300]
        else:
            self.record.setdefault("outcome", "ok")
        emit(self.record)
        _narration.info("canonical %s", logfmt(self.record))
        return False


# The event for the unit of work currently in progress, by kind ("run", "article").
#
# Ambient rather than a parameter because the code that has something to report
# is usually several layers below the code that opened the event: a provider
# knows what a completion cost, and threading an event down through the digest
# generator to reach it would add a parameter to every signature in between and
# say nothing about what any of them do.
_CURRENT = {}


def current(kind):
    """The open event of that kind, or None when no such work is in progress."""
    return _CURRENT.get(kind)


@contextmanager
def as_current(kind, event):
    """Make `event` the ambient event of that kind for the duration of the block."""
    previous = _CURRENT.get(kind)
    _CURRENT[kind] = event
    try:
        yield event
    finally:
        _CURRENT[kind] = previous


def tally(kind, key, amount=1):
    """Add to a counter on the current event, doing nothing when there is none.

    Lets a call site count something unconditionally instead of guarding every
    increment with a check for whether anybody is listening.
    """
    event = _CURRENT.get(kind)
    if event is not None:
        event.add(key, amount)
