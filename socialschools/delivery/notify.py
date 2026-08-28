"""Delivering one notification across every configured channel.

Content is generated once per distinct language actually requested and shared by
everyone who wants that language, so nothing is translated or summarised more
often than someone asked for it.
"""
import logging

from ..config import get_config
from .admin import notify_admin
from .gmail import send_email
from .pushbullet import send_pushbullet
from .recipients import parse_api_keys, parse_recipients

logger = logging.getLogger(__name__)

_NO_CHANNELS = "Set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS; nobody is being notified."


def _warn_no_channels():
    logger.warning(
        "No notification channels configured; set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS"
    )
    notify_admin("No notification channels configured", _NO_CHANNELS)


def send_notification(title, body, api_keys=None):
    """Send the same title and body to everyone, in whatever language it is already in."""
    cfg = get_config()
    if api_keys is None:
        api_keys = parse_api_keys(cfg.PUSHBULLET_API_KEYS)
    elif isinstance(api_keys, str):
        api_keys = parse_api_keys(api_keys)

    email_recipients = parse_api_keys(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")

    if not api_keys and not email_recipients:
        _warn_no_channels()
        return

    if api_keys:
        send_pushbullet(title, body, api_keys)
    if email_recipients:
        send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD, email_recipients)


def send_multilingual_notification(content_by_language):
    """Route each recipient to the content generated for their own language.

    content_by_language maps language code -> (title, body). A language missing
    from it is skipped, since nothing was generated for it.
    """
    cfg = get_config()
    pushbullet = parse_recipients(cfg.PUSHBULLET_API_KEYS)
    email = parse_recipients(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")

    if not pushbullet and not email:
        _warn_no_channels()
        return

    languages = {r.language for r in pushbullet.values()} | {r.language for r in email.values()}
    for language in languages:
        if language not in content_by_language:
            logger.warning(f"No content generated for language '{language}'; skipping its recipients")
            continue
        title, body = content_by_language[language]
        tokens = {name: r.value for name, r in pushbullet.items() if r.language == language}
        addresses = {name: r.value for name, r in email.items() if r.language == language}
        if tokens:
            send_pushbullet(title, body, tokens)
        if addresses:
            send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD, addresses)
