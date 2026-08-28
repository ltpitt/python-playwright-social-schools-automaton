from unittest.mock import patch

from socialschools.delivery.admin import notify_admin


def _admin_config(cfg, **overrides):
    cfg.EMAIL_SENDER = "sender@example.com"
    cfg.EMAIL_APP_PASSWORD = "app_password"
    cfg.ADMIN_PUSHBULLET_API_KEY = overrides.get("ADMIN_PUSHBULLET_API_KEY", "")
    cfg.ADMIN_EMAIL = overrides.get("ADMIN_EMAIL", "")
    return cfg


def test_notify_admin_noop_when_unconfigured(mock_config):
    _admin_config(mock_config)
    with patch('socialschools.delivery.admin.send_pushbullet') as mock_push, \
         patch('socialschools.delivery.admin.send_email') as mock_email:
        notify_admin("Something broke")
    mock_push.assert_not_called()
    mock_email.assert_not_called()


def test_notify_admin_sends_to_both_channels(mock_config):
    _admin_config(mock_config, ADMIN_PUSHBULLET_API_KEY="o.admin",
                  ADMIN_EMAIL="admin@example.com")
    with patch('socialschools.delivery.admin.send_pushbullet') as mock_push, \
         patch('socialschools.delivery.admin.send_email') as mock_email:
        notify_admin("Login failed", "extra detail", exc=ValueError("boom"))

    title, body, keys = mock_push.call_args[0]
    assert title == "[Social Schools admin] Login failed"
    assert "extra detail" in body
    assert "ValueError: boom" in body
    assert keys == {"admin": "o.admin"}

    email_title, email_body, sender, password, recipients = mock_email.call_args[0]
    assert email_title == title
    assert recipients == {"admin": "admin@example.com"}
    assert sender == "sender@example.com"
    assert password == "app_password"
    assert "extra detail" in email_body


def test_notify_admin_never_raises_when_channel_fails(mock_config):
    _admin_config(mock_config, ADMIN_PUSHBULLET_API_KEY="o.admin",
                  ADMIN_EMAIL="admin@example.com")
    with patch('socialschools.delivery.admin.send_pushbullet',
               side_effect=RuntimeError("push down")), \
         patch('socialschools.delivery.admin.send_email',
               side_effect=RuntimeError("smtp down")) as mock_email:
        notify_admin("Digest degraded")
    # Email is still attempted even though Pushbullet blew up first.
    mock_email.assert_called_once()
