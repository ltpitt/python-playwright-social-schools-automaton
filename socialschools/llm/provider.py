"""Choosing the configured backend, lazily."""
from ..config import get_config
from .base import LLMProvider
from .copilot import CopilotCliProvider
from .openai_compatible import OpenAICompatibleProvider


def get_provider() -> LLMProvider:
    """Build the configured LLM provider. Called only from the Digest path."""
    cfg = get_config()
    provider = (cfg.LLM_PROVIDER or "copilot").strip().lower()
    if provider == "copilot":
        return CopilotCliProvider()
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=cfg.LLM_BASE_URL,
            model=cfg.LLM_MODEL,
            api_key=cfg.LLM_API_KEY,
            timeout=cfg.LLM_TIMEOUT,
            reasoning_effort=cfg.LLM_REASONING_EFFORT,
            structured_output=cfg.LLM_STRUCTURED_OUTPUT,
        )
    raise RuntimeError(
        f"Unknown LLM_PROVIDER {provider!r}; expected 'copilot' or 'openai_compatible'"
    )
