"""Command line entry point: `python -m socialschools`."""
import argparse
import logging
import traceback

from playwright.sync_api import sync_playwright

from .delivery.admin import notify_admin
from .logging_setup import configure_logging
from .pipeline import run

logger = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="socialschools", description="Social Schools news automation")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process every article even if already seen, without updating state",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show debug detail on screen (the run report always has it)",
    )
    verbosity.add_argument(
        "-q", "--quiet", action="store_true",
        help="Show warnings and errors only",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging(
        console_level="DEBUG" if args.verbose else "WARNING" if args.quiet else None)
    try:
        with sync_playwright() as playwright:
            run(playwright, force=args.force)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        notify_admin("Run aborted with a fatal error", "No further articles were processed.", exc=e)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
