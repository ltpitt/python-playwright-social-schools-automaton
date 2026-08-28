# Pluggable LLM providers behind a single seam

Digest generation no longer talks to the Copilot CLI directly. Model access goes through a small `LLMProvider` seam (`complete(prompt) -> str` and `health_check()`), built lazily by a `get_provider()` factory that reads config. Two providers ship:

- `copilot` (default) — the GitHub Copilot CLI in non-interactive, tool-free mode (ADR 0001/0002). Behavior is unchanged.
- `openai_compatible` — a single HTTP adapter for any OpenAI-compatible `/chat/completions` endpoint, configured by `LLM_BASE_URL` + `LLM_MODEL` + optional `LLM_API_KEY`.

**Why one OpenAI-compatible adapter instead of per-provider integrations:** the OpenAI `/chat/completions` shape is a de-facto standard. A single adapter reaches local/LAN **Ollama** (`http://host:11434/v1`), **OpenRouter**, and most cloud providers (including low-cost ones) with no provider-specific code. Adding "Ollama support" and "OpenRouter support" separately would be redundant surface area for the same wire format.

**Why the seam is lazy:** `get_provider()` is only ever called from the Digest code path. When `DIGEST_ENABLED = false` (Translation mode), no provider is constructed, no health check runs, and no LLM library/HTTP client is touched. Full-local-free translation stays completely free of LLM machinery — this is a first-class mode, not a degraded one (see CONTEXT.md).

**Security — the no-tools invariant extends to every provider (ADR 0002):** article and attachment text is untrusted input. Every provider must remain a pure text transformer. The `openai_compatible` payload therefore never includes a `tools`/`functions` key and sets `stream: false`, the HTTP equivalent of Copilot's `-p` no-tools mode. A regression test (`test_openai_compatible_never_sends_tools`) guards this alongside the existing Copilot `--tool` guard.

**Trade-off / consequences:**
- **Data egress varies by provider.** Local Ollama keeps school/child content **on your network** — a privacy win that directly serves the "privacy concerns are valid" principle. OpenRouter and other cloud endpoints send content to a **third party**, broader exposure than ADR 0001's GitHub-only path. The choice is the operator's, made explicit via `LLM_PROVIDER`/`LLM_BASE_URL`.
- The retry + fallback logic in `generate_digest` is provider-agnostic and now applies to all providers unchanged.
- `LLM_TIMEOUT` is configurable because local models on modest hardware can be slow.
- Unknown `LLM_PROVIDER` values fail fast with a clear error rather than silently defaulting.
