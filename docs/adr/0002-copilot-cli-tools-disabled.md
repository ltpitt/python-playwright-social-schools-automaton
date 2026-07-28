# Copilot CLI runs with all tools disabled

When generating a Digest, the Copilot CLI is invoked in non-interactive mode (`-p` flag) which does not activate any agentic tools — no shell, file, or URL access. The application enforces this via a centralized constant `_COPILOT_TOOL_FREE_ARGS = ("copilot", "--no-color")` and a module-level `assert` that fails at import time if any `--tool` flag ever drifts into that constant. All Copilot calls go through the single `_run_copilot()` helper.

**Why:** Article bodies and, especially, extracted PDF/Word text are **untrusted input** pulled from the school website. An agentic CLI with tools enabled could be steered by a malicious or accidental instruction embedded in that text into running shell commands or touching the filesystem (prompt injection). Restricting to non-interactive `-p` mode reduces the model to a pure text transformer, so the worst case of a poisoned attachment is a low-quality Digest, never code execution.

**Consequences:**
- The CLI cannot fetch attachments itself — the pipeline must download and extract text before calling the model. This is deliberate; do not "simplify" by letting the agent fetch URLs.
- The `_COPILOT_TOOL_FREE_ARGS` constant and the import-time assertion are the regression gate. Any future change that adds `--tool` flags will fail at startup.
