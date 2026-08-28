"""Remembering which Articles have already been delivered.

An Article is recorded only once it was fully processed AND every notification
was sent, so a crash between generating and delivering means a retry rather than
a post nobody ever sees.
"""
import json
import logging
import os

from . import paths
from .delivery.admin import notify_admin

logger = logging.getLogger(__name__)


def load_processed_articles(path=None):
    path = path or paths.PROCESSED_ARTICLES_FILE
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"Error loading processed articles: {e}")
        return []


def save_processed_article(article_id, path=None):
    path = path or paths.PROCESSED_ARTICLES_FILE
    try:
        processed = load_processed_articles(path)
        if article_id in processed:
            return False
        processed.append(article_id)
        with open(paths.ensure_parent(path), 'w') as f:
            json.dump(processed, f)
        return True
    except Exception as e:
        logger.error(f"Error saving processed article: {e}")
        notify_admin("Could not persist processed article state", f"Article: {article_id}", exc=e)
        return False
