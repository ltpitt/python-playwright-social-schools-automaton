# Model access via the GitHub Copilot CLI

The pipeline turns raw Article/Attachment text into a Digest by shelling out to the GitHub Copilot CLI in non-interactive mode (`copilot --no-color -p "…"`, no tools), rather than calling a hosted LLM API with a key or running a local model. The application does not pin a model — it uses whatever the CLI's default is. The `loop.sh` development tool passes `--model gpt-5.4-mini` for its own analysis step, but that is outside the application.

**Why:** Inference runs in the cloud via a CLI the user already has installed and authenticated, so it is **host-agnostic** — it runs anywhere with internet and Node. Today it runs on the user's Mac via cron; the Windows PC is a possible future home (Task Scheduler). Local inference was ruled out on the alternative targets that were considered: the GTX 760 is compute-capability 3.0, below Ollama's 5.0 floor, and a Raspberry Pi 3 lacks the RAM to co-host Chromium and any model. Cost of hosted inference at this volume (a handful of newsletters/month) is negligible, and the Copilot CLI's non-interactive mode makes it a zero-marginal-cost backend.

**Trade-off / consequences:**
- Article text (school/child content) leaves the local network to GitHub's Copilot backend. The user has accepted cloud inference.
- Consumes the Copilot plan's premium-request budget; fine at current low volume, would need revisiting at high volume.
- Access is placed behind a single interface (`_run_copilot`) so a local backend (e.g. Ollama on an ≥8 GB box) can be added later as a config switch, not a rewrite.

**Update (2026-08-25):** the `loop.sh` development tool mentioned above was retired. It asked a model to read the whole source file and suggest improvements; `tools/goal.py` (ADR 0006) does something narrower and measurable instead, so `loop.sh` was deleted rather than maintained. The `_run_copilot` seam anticipated here duly became `socialschools.llm.copilot.run_copilot`, one provider among several (ADR 0004).
