"""Telling the admin what went wrong, on a channel parents never see.

Best-effort by construction: an admin channel that is down must not break the
run or cause an otherwise-successful Article to be retried forever. Every
failure here is swallowed and logged.
"""
import logging
import traceback

from ..config import get_config
from .gmail import send_email
from .pushbullet import send_pushbullet

logger = logging.getLogger(__name__)


def format_admin_alert(summary, detail=None, exc=None):
    sections = [summary]
    if detail:
        sections.append(str(detail))
    if exc is not None:
        sections.append(f"{type(exc).__name__}: {exc}")
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        if trace:
            sections.append(trace)
    return "\n\n".join(sections)


def notify_admin(summary, detail=None, exc=None):
    """Alert the admin channel about a problem in this run. Never raises."""
    try:
        cfg = get_config()
    except Exception as e:
        logger.error(f"Admin alert skipped, config unavailable: {e}")
        return

    if not cfg.ADMIN_PUSHBULLET_API_KEY and not cfg.ADMIN_EMAIL:
        return

    title = f"[Social Schools admin] {summary}"
    body = format_admin_alert(summary, detail, exc)

    if cfg.ADMIN_PUSHBULLET_API_KEY:
        try:
            send_pushbullet(title, body, {"admin": cfg.ADMIN_PUSHBULLET_API_KEY})
        except Exception as e:
            logger.error(f"Failed to send admin Pushbullet alert: {e}")
    if cfg.ADMIN_EMAIL:
        try:
            send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD,
                       {"admin": cfg.ADMIN_EMAIL})
        except Exception as e:
            logger.error(f"Failed to send admin email alert: {e}")
