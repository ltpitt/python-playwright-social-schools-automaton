import json
from unittest.mock import Mock, patch

import pytest

from socialschools.delivery.notify import send_multilingual_notification, send_notification


def test_send_notification(mock_config):
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", "Test:test_key")
        mock_post.assert_called_once()


def test_send_notification_with_single_key_posts_once(mock_config):
    """Test that a single 'name:token' entry results in exactly one push"""
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", "Test:test_key")
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test_key"


def test_send_notification_with_multiple_keys_pushes_to_each_recipient():
    """Test that the same notification is pushed individually to each named recipient"""
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", api_keys={"Test": "test_key", "Partner": "partner_key"})
        assert mock_post.call_count == 2
        sent_keys = [call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list]
        assert sent_keys == ["Bearer test_key", "Bearer partner_key"]


def test_send_notification_uses_configured_api_keys(mock_config):
    """Test that send_notification falls back to Config.PUSHBULLET_API_KEYS when not passed explicitly"""
    mock_config.PUSHBULLET_API_KEYS = "Test:test_key,Partner:partner_key,Grandma:another_key"
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body")
        assert mock_post.call_count == 3
        sent_keys = [call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list]
        assert sent_keys == ["Bearer test_key", "Bearer partner_key", "Bearer another_key"]


def test_send_notification_raises_on_http_error():
    """Test send_notification propagates HTTP errors so articles stay unmarked for retry"""
    import requests as req_lib
    with patch('requests.post') as mock_post:
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = req_lib.exceptions.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_response
        with pytest.raises(req_lib.exceptions.HTTPError):
            send_notification("Test", "Body", "Test:bad_key")


def test_send_notification_sends_email_when_configured(mock_config):
    """Email is sent (in addition to Pushbullet) when EMAIL_RECIPIENTS is set"""
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com,Partner:partner@example.com"
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        mock_post.return_value.status_code = 200
        server = mock_smtp.return_value.__enter__.return_value
        send_notification("Test Title", "Test Body")
        server.login.assert_called_once_with("sender@gmail.com", "app_password")
        assert server.send_message.call_count == 2
        sent_to = [call.args[0]["To"] for call in server.send_message.call_args_list]
        assert sent_to == ["you@example.com", "partner@example.com"]


def test_send_notification_email_only_skips_pushbullet(mock_config):
    """With no Pushbullet keys but email configured, only email is sent"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com"
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        send_notification("Test Title", "Test Body")
        mock_post.assert_not_called()
        server = mock_smtp.return_value.__enter__.return_value
        server.send_message.assert_called_once()


def test_send_notification_no_channels_is_noop(mock_config):
    """With neither Pushbullet nor email configured, nothing is sent"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_RECIPIENTS = ""
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        send_notification("Test Title", "Test Body")
        mock_post.assert_not_called()
        mock_smtp.assert_not_called()


def test_send_notification_email_missing_sender_raises(mock_config):
    """EMAIL_RECIPIENTS set but EMAIL_SENDER/EMAIL_APP_PASSWORD empty raises for retry"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_SENDER = ""
    mock_config.EMAIL_APP_PASSWORD = ""
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com"
    with patch('smtplib.SMTP_SSL') as mock_smtp:
        with pytest.raises(ValueError):
            send_notification("Test Title", "Test Body")
        mock_smtp.assert_not_called()


def test_send_multilingual_notification_routes_each_recipient_to_its_language(mock_config):
    """Each recipient only receives the content generated for their own language"""
    mock_config.PUSHBULLET_API_KEYS = "Davide:token_it:it,Daniela:token_en:en"
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "Mamma:mamma@example.com:it"

    content = {
        "it": ("Titolo", "Corpo"),
        "en": ("Title", "Body"),
    }
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        mock_post.return_value.status_code = 200
        send_multilingual_notification(content)

        pushed = {
            call.kwargs["headers"]["Authorization"]: json.loads(call.kwargs["data"])
            for call in mock_post.call_args_list
        }
        assert pushed["Bearer token_it"]["title"] == "Titolo"
        assert pushed["Bearer token_en"]["title"] == "Title"

        server = mock_smtp.return_value.__enter__.return_value
        server.send_message.assert_called_once()
        sent_message = server.send_message.call_args.args[0]
        assert sent_message["Subject"] == "Titolo"
        assert sent_message["To"] == "mamma@example.com"


def test_send_multilingual_notification_skips_language_without_content(mock_config):
    """A configured language missing from content_by_language is skipped, not sent empty"""
    mock_config.PUSHBULLET_API_KEYS = "Davide:token_it:it"
    with patch('requests.post') as mock_post:
        send_multilingual_notification({})
        mock_post.assert_not_called()


def test_send_notification_error(mock_config):
    """Test send_notification propagates network errors for retry-on-next-run"""
    with patch('requests.post', side_effect=Exception("Network error")):
        with pytest.raises(Exception, match="Network error"):
            send_notification("Test Title", "Test Body", "Test:test_key")


def test_send_notification_with_custom_api_key():
    """Test send_notification with custom API key"""
    with patch('requests.post') as mock_post:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        send_notification("Test", "Body", "Custom:custom_api_key")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        headers = call_args[1]['headers']
        assert headers['Authorization'] == "Bearer custom_api_key"
