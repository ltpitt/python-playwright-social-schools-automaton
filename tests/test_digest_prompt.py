"""What the shipped Digest prompt template must say, exercised through generate_digest."""
import json
from unittest.mock import Mock, patch

from socialschools.digest.generate import generate_digest


def _valid_cli_result():
    result = Mock()
    result.returncode = 0
    result.stdout = json.dumps({
        "translated_title": "Title", "tldr": "Summary", "topics": [],
    })
    return result


def test_generate_digest_prompt_instructs_attachment_source_reference(mock_config):
    """Test the prompt tells the model to cite the attachment filename for info sourced from one"""
    with patch('subprocess.run', return_value=_valid_cli_result()) as mock_run:
        generate_digest("Title", "Body", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "see filename.pdf" in prompt


def test_generate_digest_prompt_demands_topic_grouping(mock_config):
    """The prompt must ask for topic grouping, a separate bring list, and no invented dates

    These assertions are the reason goal.py cannot quietly drop a rule: a turn
    that deletes one fails the suite and a human has to agree to the loss.
    """
    with patch('subprocess.run', return_value=_valid_cli_result()) as mock_run:
        generate_digest("Title", "Body", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Group the message into topics" in prompt
        assert "ONE item per entry" in prompt
        assert "NEVER invent a date" in prompt
        assert "Order topics by urgency" in prompt
        assert "which group or class" in prompt
        assert "date not specified" in prompt
        assert "Do not repeat items listed in 'bring' within 'actions'" in prompt
        assert "24-hour HH:MM" in prompt
        assert "Never use" in prompt and "AM/PM" in prompt
        assert "at most ONE entry per real-world event" in prompt
        assert "request for parents to volunteer" in prompt


def test_generate_digest_prompt_demands_a_substantive_tldr(mock_config):
    """A tldr describing the message ('this message provides...') helps no parent"""
    with patch('subprocess.run', return_value=_valid_cli_result()) as mock_run:
        generate_digest("Title", "Body", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "state the substance rather than describe the message" in prompt
        assert "This message provides important information" in prompt
        assert "zero-padded two-digit day" in prompt
        assert "NEVER " in prompt and "copy the item's original wording through untranslated" in prompt
        assert "ONE action entry carrying every time and instruction" in prompt
