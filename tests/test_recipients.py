import pytest

from socialschools.delivery.recipients import (
    get_requested_languages,
    parse_api_keys,
    parse_recipients,
)
from socialschools.models import Recipient


def test_parse_api_keys_splits_and_strips():
    assert parse_api_keys("Partner: key1 , Grandma:key2") == {"Partner": "key1", "Grandma": "key2"}


def test_parse_api_keys_rejects_entry_missing_colon():
    with pytest.raises(ValueError):
        parse_api_keys("just_a_key_no_name")


def test_parse_api_keys_rejects_entry_missing_name():
    with pytest.raises(ValueError):
        parse_api_keys(":key_without_a_name")


def test_parse_api_keys_parses_email_recipients():
    assert parse_api_keys("You:you@example.com,Partner:p@example.com",
                          field_name="EMAIL_RECIPIENTS") == {
        "You": "you@example.com", "Partner": "p@example.com"}


def test_parse_recipients_defaults_to_translation_language(mock_config):
    """Entries without a ':language' suffix fall back to TRANSLATION_LANGUAGE"""
    mock_config.TRANSLATION_LANGUAGE = "en"
    parsed = parse_recipients("Davide:token1,Daniela:token2")
    assert parsed["Davide"].value == "token1"
    assert parsed["Davide"].language == "en"
    assert parsed["Daniela"].language == "en"


def test_parse_recipients_honors_per_recipient_language(mock_config):
    parsed = parse_recipients("Davide:token1:it,Daniela:token2:en")
    assert parsed["Davide"] == Recipient(value="token1", language="it")
    assert parsed["Daniela"] == Recipient(value="token2", language="en")


def test_parse_recipients_rejects_empty_language():
    with pytest.raises(ValueError):
        parse_recipients("Davide:token1:")


def test_parse_recipients_rejects_too_many_colons():
    with pytest.raises(ValueError):
        parse_recipients("Davide:token1:it:extra")


def test_get_requested_languages_combines_pushbullet_and_email(mock_config):
    mock_config.PUSHBULLET_API_KEYS = "Davide:token1:it"
    mock_config.EMAIL_RECIPIENTS = "Daniela:d@example.com:en"
    assert get_requested_languages() == {"it", "en"}


def test_get_requested_languages_falls_back_to_translation_language(mock_config):
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_RECIPIENTS = ""
    mock_config.TRANSLATION_LANGUAGE = "fr"
    assert get_requested_languages() == {"fr"}
