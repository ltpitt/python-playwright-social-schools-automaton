import json
from unittest.mock import Mock, patch

import pytest

from socialschools.digest.generate import generate_digest, readable_filename
from socialschools.models import Attachment, Digest


def test_readable_filename_drops_the_storage_uuid():
    """The model copies the filename into the brief, so the hex reaches a parent"""
    assert readable_filename(
        "class-letter-096058d0-bf7c-4714-ba6a-67b17716ac7a.pdf") == "class-letter.pdf"


def test_readable_filename_leaves_an_ordinary_name_alone():
    assert readable_filename("class-letter.pdf") == "class-letter.pdf"
    assert readable_filename("trip-2026-09-01.docx") == "trip-2026-09-01.docx"


def test_generate_digest(mock_config):
    """Test Digest generation via Copilot CLI subprocess call returns dict"""
    digest_data = {
        "translated_title": "School Trip",
        "tldr": "Children need gym shoes",
        "topics": [{
            "heading": "School trip",
            "actions": ["15 Aug - bring gym shoes"],
            "bring": [],
            "notes": ["16 Aug - school closed"],
        }],
    }
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(digest_data)

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = generate_digest("School Trip", "Body text", [])

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "copilot"
        assert "-p" in cmd
        prompt_idx = cmd.index("-p") + 1
        assert "School Trip" in cmd[prompt_idx]
        assert "Body text" in cmd[prompt_idx]
        assert "--no-color" in cmd
        assert isinstance(result, Digest)
        assert result.translated_title == "School Trip"
        assert result.topics[0].actions == ["15 Aug - bring gym shoes"]


def test_generate_digest_with_attachments(mock_config):
    """Test Digest generation includes attachment text in prompt"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Form Required",
        "tldr": "A form must be returned",
        "topics": [{"heading": "Form", "actions": ["15 Aug - sign and return the form"],
                    "bring": [], "notes": []}],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [Attachment(
            filename="form.pdf", url="http://example.com/form.pdf",
            filetype="pdf", text="Sign and return by 15 Aug",
        )])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "form.pdf" in prompt
        assert "Sign and return by 15 Aug" in prompt


def test_generate_digest_cli_not_found(mock_config):
    """Test generate_digest raises RuntimeError when copilot CLI is missing"""
    with patch('subprocess.run', side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Copilot CLI not found"):
            generate_digest("Title", "Body", [])


def test_generate_digest_cli_failure(mock_config):
    """Test generate_digest raises RuntimeError on non-zero CLI exit"""
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stderr = "auth error"

    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(RuntimeError, match="Copilot CLI returned code 1"):
            generate_digest("Title", "Body", [])


def test_generate_digest_retry_on_invalid_json(mock_config):
    """Test generate_digest retries once when response is not valid JSON"""
    valid_json = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    invalid_result = Mock()
    invalid_result.returncode = 0
    invalid_result.stdout = "not valid json at all"

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = valid_json

    with patch('subprocess.run', side_effect=[invalid_result, valid_result]) as mock_run:
        result = generate_digest("Title", "Body", [])

        assert mock_run.call_count == 2
        assert result.translated_title == "Title"


def test_generate_digest_fallback_on_second_failure(mock_config):
    """Test that two consecutive invalid CLI responses yield a safe fallback Digest"""
    bad_result = Mock()
    bad_result.returncode = 0
    bad_result.stdout = "not valid json at all"

    with patch('subprocess.run', return_value=bad_result) as mock_run:
        result = generate_digest("School Trip", "Body text", [])

        assert mock_run.call_count == 2
        assert isinstance(result, Digest)
        assert result.translated_title == "School Trip"
        assert result.topics == []


def test_generate_digest_includes_failed_attachment_in_prompt(mock_config):
    """Test that failed attachments are named in the Copilot prompt as unreadable placeholders"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [Attachment(
            filename="form.pdf", url="http://x/form.pdf",
            filetype="pdf", text="", failed=True,
        )])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "form.pdf" in prompt
        assert "could not be extracted" in prompt


def test_generate_digest_includes_pre_scan_hints_in_prompt(mock_config):
    """Test that detected dates/instructions are surfaced to the model as pre-scan hints"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Hand in the form",
        "topics": [{"heading": "Form", "actions": ["15 aug - lever het formulier in"],
                    "bring": [], "notes": []}],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Gelieve het formulier voor 15 aug in te leveren.", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Pre-scan hints" in prompt
        assert "15 aug" in prompt


def test_generate_digest_omits_pre_scan_hints_when_none_found(mock_config):
    """Test that the prompt has no hints section when no dates/instructions are detected"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Nothing notable.",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Just a friendly note with no dates.", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Pre-scan hints" not in prompt


def test_generate_digest_retry_prompt_demands_target_language(mock_config):
    """Test the retry prompt explicitly requires the configured reader language"""
    mock_config.TRANSLATION_LANGUAGE = "it"
    invalid_result = Mock()
    invalid_result.returncode = 0
    invalid_result.stdout = "not valid json"

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = json.dumps({
        "translated_title": "Titolo",
        "tldr": "Riassunto",
        "topics": [],
    })

    with patch('subprocess.run', side_effect=[invalid_result, valid_result]) as mock_run:
        generate_digest("Title", "Body", [])

        retry_prompt = mock_run.call_args_list[1][0][0][
            mock_run.call_args_list[1][0][0].index("-p") + 1
        ]
        assert "written in it" in retry_prompt


def test_generate_digest_retries_when_first_response_has_no_content(mock_config):
    """Test that an empty-content digest (valid JSON, but no tldr/items) triggers a retry"""
    empty_result = Mock()
    empty_result.returncode = 0
    empty_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "",
        "topics": [],
    })

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Now with content",
        "topics": [],
    })

    with patch('subprocess.run', side_effect=[empty_result, valid_result]) as mock_run:
        result = generate_digest("Title", "Body", [])

        assert mock_run.call_count == 2
        assert result.tldr == "Now with content"


def test_generate_digest_via_openai_compatible_provider(mock_config):
    """generate_digest routes through the HTTP provider when configured, not the CLI"""
    mock_config.LLM_PROVIDER = "openai_compatible"
    mock_config.LLM_BASE_URL = "http://localhost:11434/v1"
    mock_config.LLM_MODEL = "llama3.1"

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": json.dumps({
        "translated_title": "School Trip",
        "tldr": "Bring shoes",
        "topics": [{"heading": "Trip", "actions": ["15 Aug - bring shoes"],
                    "bring": [], "notes": []}],
    })}}]}

    with patch('requests.post', return_value=mock_resp) as mock_post, \
            patch('subprocess.run') as mock_run:
        result = generate_digest("School Trip", "Body", [])

    mock_post.assert_called_once()
    mock_run.assert_not_called()
    assert isinstance(result, Digest)
    assert result.translated_title == "School Trip"
