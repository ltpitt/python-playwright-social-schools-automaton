"""What every backend must offer, and where a completion's cost is recorded."""
from .. import events


class LLMProvider:
    """Interface for turning a prompt into completion text."""

    def health_check(self) -> None:
        """Fail fast (raise RuntimeError) if the backend is not reachable."""
        raise NotImplementedError

    def complete(self, prompt: str) -> str:
        """Return the model's completion text for the given prompt."""
        raise NotImplementedError


# What the last completion cost, in tokens/money/seconds. A module global rather
# than a return value because get_provider() builds a fresh provider per call;
# only the evaluation harness reads it, and only right after a generation.
_LAST_USAGE = {}


def get_last_llm_usage():
    """Usage of the most recent completion. Empty when the backend reports none."""
    return dict(_LAST_USAGE)


def record_usage(usage):
    """Note what a completion cost, both for the caller and for the canonical events."""
    _LAST_USAGE.clear()
    _LAST_USAGE.update(usage)
    # Cost and latency belong to the unit of work that caused them, so they can
    # be compared across runs rather than only read once, live.
    for kind in ("article", "run"):
        event = events.current(kind)
        if event is None:
            continue
        event.add("llm_calls")
        for field, key in (("llm_tokens", "total_tokens"), ("llm_cost_usd", "cost_usd"),
                           ("llm_ms", "latency_s")):
            value = usage.get(key)
            if isinstance(value, (int, float)):
                event.add(field, round(value * 1000, 1) if key == "latency_s" else value)
