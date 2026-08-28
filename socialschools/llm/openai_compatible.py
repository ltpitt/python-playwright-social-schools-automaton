"""Any OpenAI-compatible /chat/completions endpoint.

One adapter covers local Ollama, OpenRouter and most cloud providers, so a
single config setting spans local, self-hosted and paid. No 'tools' or
'functions' key is ever sent (ADR 0002).
"""
import json
import logging
import time

import requests

from ..digest.schema import DIGEST_JSON_SCHEMA
from .base import LLMProvider, record_usage

logger = logging.getLogger(__name__)

# A 4xx from a chat endpoint most often means "I don't know this option" rather
# than "your request is malformed", so an unsupported extra can be dropped and retried.
UNSUPPORTED_OPTION_STATUSES = (400, 404, 422)


def usage_from_response(data, latency_s):
    """Token counts, and money when the endpoint reports it, for one completion."""
    usage = data.get("usage") or {}
    recorded = {"latency_s": round(latency_s, 2), "requests": 1}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if isinstance(usage.get(key), int):
            recorded[key] = usage[key]
    if isinstance(usage.get("cost"), (int, float)):
        recorded["cost_usd"] = float(usage["cost"])
    return recorded


class OpenAICompatibleProvider(LLMProvider):

    def __init__(self, base_url, model, api_key="", timeout=120,
                 reasoning_effort="", structured_output=True):
        if not base_url:
            raise RuntimeError("LLM_BASE_URL is required for the 'openai_compatible' provider")
        if not model:
            raise RuntimeError("LLM_MODEL is required for the 'openai_compatible' provider")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self.structured_output = structured_output
        # Only OpenRouter accepts (and answers) the cost-reporting flag; sending
        # it to Ollama or a plain OpenAI endpoint risks a rejected request.
        self.reports_cost = "openrouter.ai" in self.base_url

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health_check(self) -> None:
        try:
            resp = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
        except requests.RequestException as e:
            raise RuntimeError(f"LLM endpoint unreachable at {self.base_url}: {e}")
        # Local/key-less servers may reject /models with 4xx; only a 5xx means the
        # endpoint itself is unhealthy. Anything reachable is good enough to proceed.
        if resp.status_code >= 500:
            raise RuntimeError(
                f"LLM endpoint health check failed ({resp.status_code}) at {self.base_url}"
            )

    def _post(self, payload):
        try:
            return requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"LLM request to {self.base_url} failed: {e}")

    def complete(self, prompt: str) -> str:
        # ADR 0002: deliberately no 'tools'/'functions' key — pure text transformer only.
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Structured extraction, not creative writing: sample deterministically.
            "temperature": 0,
        }
        if self.structured_output:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": DIGEST_JSON_SCHEMA}
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.reports_cost:
            payload["usage"] = {"include": True}

        started = time.monotonic()
        resp = self._post(payload)
        if resp.status_code in UNSUPPORTED_OPTION_STATUSES and "response_format" in payload:
            # Not every model behind an OpenAI-compatible endpoint implements
            # json_schema. Degrade to prompt-only JSON for the rest of this run.
            logger.warning(
                f"{self.model} rejected structured output ({resp.status_code}); "
                "retrying without a response schema")
            self.structured_output = False
            payload.pop("response_format")
            resp = self._post(payload)
        if resp.status_code != 200:
            logger.error(f"LLM endpoint error body:\n{resp.text}")
            raise RuntimeError(f"LLM endpoint returned status {resp.status_code}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise RuntimeError(f"Unexpected LLM response shape: {e}")
        record_usage(usage_from_response(data, time.monotonic() - started))
        return content
