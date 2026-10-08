import json
from unittest.mock import Mock, patch

import pytest

from socialschools.llm.base import get_last_llm_usage
from socialschools.llm.copilot import (
    TOOL_FREE_ARGS,
    CopilotCliProvider,
    check_copilot_available,
)
from socialschools.llm.openai_compatible import OpenAICompatibleProvider
from socialschools.llm.provider import get_provider


def _ok_response(content="{}", usage=None):
    resp = Mock()
    resp.status_code = 200
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    resp.json.return_value = body
    return resp


# =============================================================================
# PROVIDER SELECTION
# =============================================================================


def test_get_provider_defaults_to_copilot(mock_config):
    """Default config selects the Copilot CLI provider"""
    assert isinstance(get_provider(), CopilotCliProvider)


def test_get_provider_openai_compatible(mock_config):
    """LLM_PROVIDER=openai_compatible builds the HTTP adapter from config"""
    mock_config.LLM_PROVIDER = "openai_compatible"
    mock_config.LLM_BASE_URL = "http://localhost:11434/v1"
    mock_config.LLM_MODEL = "llama3.1"

    provider = get_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.model == "llama3.1"


def test_get_provider_unknown_raises(mock_config):
    """An unrecognized LLM_PROVIDER fails fast with a clear error"""
    mock_config.LLM_PROVIDER = "bogus"
    with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER"):
        get_provider()


# =============================================================================
# COPILOT CLI PROVIDER
# =============================================================================


def test_copilot_command_has_no_tool_flags():
    """ADR 0002 regression: Copilot invocation must never include tool-access flags"""
    cmd = [*TOOL_FREE_ARGS, "-p", "sample prompt"]
    assert all("--tool" not in arg for arg in cmd), \
        "ADR 0002: tool flags must not appear in TOOL_FREE_ARGS"
    assert "-p" in cmd, "Non-interactive flag -p must be present"
    assert "--no-color" in cmd


def test_check_copilot_available_success():
    """Test startup check passes when copilot responds with exit 0"""
    mock_result = Mock()
    mock_result.returncode = 0
    with patch('subprocess.run', return_value=mock_result):
        check_copilot_available()  # should not raise


def test_check_copilot_available_not_found():
    """Test startup check raises RuntimeError when copilot is not in PATH"""
    with patch('subprocess.run', side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Copilot CLI not found"):
            check_copilot_available()


def test_check_copilot_available_failure():
    """Test startup check raises RuntimeError on non-zero exit"""
    mock_result = Mock()
    mock_result.returncode = 1
    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(RuntimeError, match="health check failed"):
            check_copilot_available()


# =============================================================================
# OPENAI-COMPATIBLE PROVIDER
# =============================================================================


def test_openai_compatible_requires_base_url_and_model():
    """The HTTP provider refuses to construct without base_url and model"""
    with pytest.raises(RuntimeError, match="LLM_BASE_URL is required"):
        OpenAICompatibleProvider(base_url="", model="x")
    with pytest.raises(RuntimeError, match="LLM_MODEL is required"):
        OpenAICompatibleProvider(base_url="http://x/v1", model="")


def test_openai_compatible_complete_returns_content():
    """A well-formed OpenAI-compatible response yields the message content"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "  hello  "}}]
    }
    with patch('requests.post', return_value=mock_resp) as mock_post:
        result = provider.complete("prompt text")
    assert result == "hello"
    url = mock_post.call_args[0][0]
    assert url == "http://x/v1/chat/completions"


def test_openai_compatible_requests_deterministic_sampling():
    """Digest extraction must not sample at the provider's creative default temperature"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
    with patch('requests.post', return_value=mock_resp) as mock_post:
        provider.complete("prompt text")
    payload = json.loads(mock_post.call_args[1]["data"])
    assert payload["temperature"] == 0


def test_openai_compatible_never_sends_tools():
    """ADR 0002 regression: the HTTP payload must never include tools/functions"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch('requests.post', return_value=mock_resp) as mock_post:
        provider.complete("prompt text")
    payload = json.loads(mock_post.call_args[1]["data"])
    assert "tools" not in payload
    assert "functions" not in payload
    assert payload["stream"] is False


def test_openai_compatible_sends_bearer_token_when_key_set():
    """An API key is sent as a Bearer token; absent key sends no Authorization header"""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with_key = OpenAICompatibleProvider(base_url="http://x/v1", model="m", api_key="secret")
    with patch('requests.post', return_value=mock_resp) as mock_post:
        with_key.complete("p")
    assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer secret"

    no_key = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with patch('requests.post', return_value=mock_resp) as mock_post:
        no_key.complete("p")
    assert "Authorization" not in mock_post.call_args[1]["headers"]


def test_openai_compatible_raises_on_error_status():
    """A non-200 status from the endpoint raises RuntimeError"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    with patch('requests.post', return_value=mock_resp):
        with pytest.raises(RuntimeError, match="returned status 401"):
            provider.complete("p")


def test_openai_compatible_asks_the_endpoint_to_enforce_the_schema():
    """A server-enforced schema removes a whole class of JSON parse failures"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with patch('requests.post', return_value=_ok_response()) as mock_post:
        provider.complete("p")
    payload = json.loads(mock_post.call_args[1]["data"])
    schema = payload["response_format"]["json_schema"]["schema"]
    assert payload["response_format"]["type"] == "json_schema"
    assert set(schema["required"]) == {"translated_title", "tldr", "topics"}


def test_openai_compatible_retries_without_schema_when_rejected():
    """Not every model implements json_schema; the run must degrade, not die"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    rejected = Mock()
    rejected.status_code = 400
    rejected.text = "response_format not supported"
    with patch('requests.post', side_effect=[rejected, _ok_response("ok")]) as mock_post:
        assert provider.complete("p") == "ok"

    assert mock_post.call_count == 2
    assert "response_format" not in json.loads(mock_post.call_args[1]["data"])
    assert provider.structured_output is False


def test_openai_compatible_omits_structured_output_when_disabled():
    provider = OpenAICompatibleProvider(
        base_url="http://x/v1", model="m", structured_output=False)
    with patch('requests.post', return_value=_ok_response()) as mock_post:
        provider.complete("p")
    assert "response_format" not in json.loads(mock_post.call_args[1]["data"])


def test_openai_compatible_sends_reasoning_effort_only_when_configured():
    """Non-reasoning models reject the option, so it must stay absent by default"""
    with patch('requests.post', return_value=_ok_response()) as mock_post:
        OpenAICompatibleProvider(base_url="http://x/v1", model="m").complete("p")
    assert "reasoning" not in json.loads(mock_post.call_args[1]["data"])

    with patch('requests.post', return_value=_ok_response()) as mock_post:
        OpenAICompatibleProvider(
            base_url="http://x/v1", model="m", reasoning_effort="High").complete("p")
    assert json.loads(mock_post.call_args[1]["data"])["reasoning"] == {"effort": "high"}


def test_openai_compatible_records_usage_for_cost_comparison():
    """Choosing between models needs the bill, not just the quality score"""
    provider = OpenAICompatibleProvider(
        base_url="https://openrouter.ai/api/v1", model="m")
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost": 0.0042}
    with patch('requests.post', return_value=_ok_response(usage=usage)) as mock_post:
        provider.complete("p")

    assert json.loads(mock_post.call_args[1]["data"])["usage"] == {"include": True}
    recorded = get_last_llm_usage()
    assert recorded["cost_usd"] == 0.0042
    assert recorded["total_tokens"] == 120
    assert recorded["requests"] == 1
    assert "latency_s" in recorded


def test_openai_compatible_asks_for_cost_only_from_openrouter():
    """Ollama and plain OpenAI endpoints can reject the cost-reporting flag"""
    provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1", model="m")
    with patch('requests.post', return_value=_ok_response()) as mock_post:
        provider.complete("p")
    assert "usage" not in json.loads(mock_post.call_args[1]["data"])
