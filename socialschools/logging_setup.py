"""Where log output goes, decided by the entry point rather than by an import.

The log file always gets everything: it is the narration behind the canonical
events in `events.jsonl`, joined to them by RUN_ID. Only the console is
quietened, so turning the terminal down never costs you evidence.

Rotating rather than truncating, because the run you want to explain is usually
the one before this one.

Configuration is an explicit call, not an import side effect: importing a module
to read one function out of it should not open a file handle in whatever
directory you happened to be standing in.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler

from . import paths
from .console import log_console
from .events import RUN_ID

MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5

_console_handler = None


def configure_logging(console_level=None):
    """Attach the file and console handlers. Safe to call more than once."""
    global _console_handler
    if _console_handler is not None:
        if console_level:
            _console_handler.setLevel(console_level)
        return

    file_handler = RotatingFileHandler(
        paths.ensure_parent(paths.RUN_REPORT_FILE),
        maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s " + RUN_ID + " %(levelname)s %(name)s %(message)s"))
    file_handler.setLevel(logging.DEBUG)

    _console_handler = RichHandler(
        console=log_console, show_path=False, show_time=False, markup=False,
        rich_tracebacks=True, log_time_format="")
    _console_handler.setLevel(
        console_level or os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO")

    logging.basicConfig(
        level=logging.DEBUG, format="%(message)s",
        handlers=[file_handler, _console_handler], force=True)


def set_console_log_level(level):
    """Change terminal verbosity. The log file is unaffected, by design."""
    if _console_handler is not None:
        _console_handler.setLevel(level)
