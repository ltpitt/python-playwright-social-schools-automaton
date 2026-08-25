"""Sending a notification by email through Gmail's SMTP server.

One message per recipient, so nobody's address is exposed to anybody else. A
failed send raises, which leaves the Article unmarked and retried next run.
"""
import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_email(title, body, sender, app_password, recipients):
    """Email every {name: address} entry individually via Gmail SMTP over TLS."""
    if not sender or not app_password:
        raise ValueError(
            "EMAIL_RECIPIENTS is set but EMAIL_SENDER and/or EMAIL_APP_PASSWORD are empty"
        )
    logger.info(f"Sending email notification with title: {title}")
    logger.debug(f"Notification body:\n{body}")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, app_password)
        for name, address in recipients.items():
            logger.debug(f"Emailing notification to recipient '{name}' <{address}>")
            message = EmailMessage()
            message["Subject"] = title
            message["From"] = sender
            message["To"] = address
            message.set_content(body)
            server.send_message(message)
    logger.info("Email notification sent")
