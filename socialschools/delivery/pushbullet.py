"""Pushing a notification to each recipient's own Pushbullet account.

One push per private, per-person token rather than a shared channel: channel
subscriptions need no approval from the owner and the channel-info API is
publicly queryable, and these notifications carry a child's name and schedule.
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

PUSHES_URL = "https://api.pushbullet.com/v2/pushes"


def send_pushbullet(title, body, api_keys):
    """Push to every {name: token} entry. Raises on the first failure."""
    logger.info(f"Sending Pushbullet notification with title: {title}")
    logger.debug(f"Notification body:\n{body}")
    params = {"type": "note", "title": title, "body": body}
    logger.debug(f"Pushing notification to {len(api_keys)} configured recipient(s)")
    for _, key in api_keys.items():
        response = requests.post(
            PUSHES_URL,
            data=json.dumps(params),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
    logger.info("Pushbullet notification sent")
