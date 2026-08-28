"""Getting an Article's identity, date and body out of the rendered feed.

Social Schools' markup is not ours and has changed under us before, so every
read here degrades rather than crashes: a missing id is derived, a missing date
is None, and the body is looked for through a list of selectors ending in one
that almost always matches something.
"""
import logging
from datetime import datetime

from ..digest.hints import parse_post_datetime

logger = logging.getLogger(__name__)

FEED_SELECTOR = "div[role='feed']"
ARTICLE_SELECTOR = "div[role='article']"
TITLE_SELECTOR = "h3"
DATE_SELECTOR = "a.meta-info"

# Ordered widest-last: the earlier selectors identify the body, the later ones
# merely contain it, and something readable beats nothing at all.
BODY_SELECTORS = (
    "span[as='div']",
    "[data-testid='article-body']",
    "[data-test='article-body']",
    "div[role='article'] span",
    "p",
    "div",
)

EXPAND_SELECTORS = (
    "[data-testid='article-body'], [data-test='article-body'], div[role='article'] span, p"
)


def get_article_id(article):
    """The feed's own id for an Article, or one derived from its title and time."""
    article_id = article.get_attribute("data-id") or article.get_attribute("id")
    if not article_id:
        logger.debug("No article ID attribute, generating from title and timestamp")
        title_el = article.query_selector(TITLE_SELECTOR)
        title = title_el.inner_text() if title_el else "unknown"
        timestamp_el = article.query_selector("time")
        timestamp = (timestamp_el.get_attribute("datetime")
                     if timestamp_el else datetime.now().isoformat())
        article_id = f"{title}_{timestamp}"
        logger.info(f"Generated article ID: {article_id}")
    return article_id


def get_article_title(article):
    title_el = article.query_selector(TITLE_SELECTOR)
    return title_el.inner_text() if title_el else "(no title)"


def get_post_date(article, today=None):
    """The post's date as 'D Mon' or 'D Mon HH:MM', or None if unavailable.

    Only the leading segment of the label is read: an edited post appends a
    second ', bijgewerkt ...' timestamp that would otherwise mask the original.
    """
    date_el = article.query_selector(DATE_SELECTOR)
    if not date_el:
        return None
    raw = date_el.inner_text()
    if not raw:
        return None
    return parse_post_datetime(raw.split(",")[0], today=today)


def expand_full_text(article):
    """Click 'Meer weergeven' when it is offered and wait for the body to appear.

    Some articles never render the expected container, and some already have
    their content in the visible DOM. Neither is a reason to abort the run.
    """
    try:
        more_button = article.query_selector("button:has-text('Meer weergeven')")
        if more_button:
            logger.info("Clicking 'Meer weergeven' to expand article text")
            try:
                more_button.click()
            except Exception as e:
                logger.warning(f"Could not click 'Meer weergeven': {e}")

        try:
            article.wait_for_selector("span[as='div']", timeout=10000)
            return
        except Exception:
            logger.warning(
                "Legacy full-text selector not found within timeout; trying a more tolerant "
                "fallback before giving up."
            )

        try:
            article.wait_for_selector(EXPAND_SELECTORS, timeout=10000)
        except Exception as fallback_error:
            logger.warning(
                "Full-text content could not be located with the legacy or fallback selectors: "
                f"{fallback_error}"
            )
    except Exception as e:
        logger.error(f"Error expanding full text: {str(e)}")


def read_visible_article_body(article):
    """The first readable body element's text, or a helpful ValueError."""
    for selector in BODY_SELECTORS:
        element = article.query_selector(selector)
        if not element:
            continue
        try:
            text = element.inner_text()
            if text and text.strip():
                return text
        except Exception as exc:
            logger.debug(f"Selector {selector!r} did not yield text: {exc}")

    raise ValueError("No readable article body found in the visible DOM")
