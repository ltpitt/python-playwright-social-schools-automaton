"""Finding a Chromium to drive.

`playwright install` is unreliable on a Raspberry Pi and downloads hundreds of
megabytes it does not need to, so a system browser is preferred when one exists
and Playwright's own download is the fallback rather than the requirement.
"""
import glob
import logging
import os
import shutil

logger = logging.getLogger(__name__)

BROWSER_NAMES = (
    "chromium-browser",
    "chromium",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
)

WELL_KNOWN_PATHS = (
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

PLAYWRIGHT_ROOTS = (
    "~/.cache/ms-playwright",
    "~/.local/share/ms-playwright",
)


def resolve_browser_executable_path():
    """A usable browser binary, or None to let Playwright use its own."""
    candidates = [os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"), *WELL_KNOWN_PATHS]

    for browser_name in BROWSER_NAMES:
        resolved = shutil.which(browser_name)
        if resolved:
            candidates.append(resolved)

    for root in PLAYWRIGHT_ROOTS:
        expanded = os.path.expanduser(root)
        if os.path.isdir(expanded):
            for pattern in ("chrome", "chrome.exe"):
                candidates.extend(
                    glob.glob(os.path.join(expanded, "**", "chrome-linux", pattern), recursive=True)
                )

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def launch_options():
    """Headless launch options, naming a system browser when one was found."""
    options = {"headless": True}
    executable_path = resolve_browser_executable_path()
    if executable_path:
        options["executable_path"] = executable_path
        logger.info(f"Using browser executable: {executable_path}")
    else:
        logger.info("No system browser executable found, using Playwright default Chromium")
    return options
