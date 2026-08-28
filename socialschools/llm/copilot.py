"""The GitHub Copilot CLI, driven non-interactively (ADR 0001, ADR 0002)."""
import logging
import subprocess
import time

from .base import LLMProvider, record_usage

logger = logging.getLogger(__name__)

# Per ADR 0001: non-interactive invocation via the -p flag.
# Per ADR 0002: the -p flag enforces no tool access. Never add --tool flags here.
TOOL_FREE_ARGS = ("copilot", "--no-color")

# ADR 0002 guard: fail at import time if tool-access flags drift into this constant.
assert not any("--tool" in arg for arg in TOOL_FREE_ARGS), (
    "ADR 0002 violation: TOOL_FREE_ARGS must not contain --tool flags"
)

TIMEOUT_SECONDS = 120


def check_copilot_available():
    """Fail fast if the Copilot CLI is not reachable before processing any Article."""
    try:
        result = subprocess.run(
            ["copilot", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError("Copilot CLI not found. Ensure 'copilot' is in PATH.")
    if result.returncode != 0:
        raise RuntimeError(f"Copilot CLI health check failed (code {result.returncode})")


def run_copilot(prompt):
    try:
        result = subprocess.run(
            [*TOOL_FREE_ARGS, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise RuntimeError("Copilot CLI not found. Ensure 'copilot' is in PATH.")
    if result.returncode != 0:
        logger.error(f"Copilot CLI stderr:\n{result.stderr}")
        raise RuntimeError(f"Copilot CLI returned code {result.returncode}")
    return result.stdout.strip()


class CopilotCliProvider(LLMProvider):
    """Default backend: the Copilot CLI in non-interactive, tool-free mode."""

    def health_check(self) -> None:
        check_copilot_available()

    def complete(self, prompt: str) -> str:
        started = time.monotonic()
        text = run_copilot(prompt)
        # The CLI bills against a request quota and reports no token counts.
        record_usage({"latency_s": round(time.monotonic() - started, 2), "requests": 1})
        return text
