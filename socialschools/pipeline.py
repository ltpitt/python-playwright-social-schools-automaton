"""The run itself: log in, walk the feed, and see each new Article through.

The rule the whole file exists to enforce: an Article is marked processed only
when it was fully handled and every notification was delivered. Anything else
leaves it unmarked so the next run tries again. Two degraded-but-delivered cases
still count, because the notification did reach parents and says what was
missing — resending it every run would only be spam.
"""
import logging
import traceback

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import events
from .config import get_config
from .delivery.admin import notify_admin
from .delivery.notify import send_multilingual_notification, send_notification
from .delivery.recipients import get_requested_languages, parse_recipients
from .digest.generate import generate_digest
from .digest.prompt import DIGEST_PROMPT_TEMPLATE
from .digest.render import render_digest_notification
from .events import Event, environment, sha8
from .llm.provider import get_provider
from .scraping.attachments import collect_attachments
from .scraping.browser import launch_options
from .scraping.feed import (
    ARTICLE_SELECTOR,
    FEED_SELECTOR,
    expand_full_text,
    get_article_id,
    get_article_title,
    get_post_date,
    read_visible_article_body,
)
from .scraping.login import login_to_website
from .state import load_processed_articles, save_processed_article
from .translate import translate

logger = logging.getLogger(__name__)

FEED_WAIT_MS = 60000


def run_event_fields(force):
    """What this run is, before it does anything: code, config, audience."""
    cfg = get_config()
    pushbullet = parse_recipients(cfg.PUSHBULLET_API_KEYS)
    email = parse_recipients(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")
    return {
        **environment(),
        "forced": force,
        "digest_enabled": cfg.DIGEST_ENABLED,
        "provider": cfg.LLM_PROVIDER,
        "model": cfg.LLM_MODEL or None,
        "structured_output": cfg.LLM_STRUCTURED_OUTPUT,
        "reasoning_effort": cfg.LLM_REASONING_EFFORT or None,
        "languages": ",".join(sorted(get_requested_languages())),
        "prompt_sha": sha8(DIGEST_PROMPT_TEMPLATE),
        "prompt_chars": len(DIGEST_PROMPT_TEMPLATE),
        "recipients_pushbullet": len(pushbullet),
        "recipients_email": len(email),
    }


def run(playwright, force=False):
    """One complete pass over the feed, reported as a single canonical event."""
    with Event("run", **run_event_fields(force)) as run_event:
        with events.as_current("run", run_event):
            _run(playwright, force)


def _run(playwright, force):
    try:
        browser = playwright.chromium.launch(**launch_options())
        context = browser.new_context()
        page = context.new_page()

        login_to_website(page)
        if "home" not in page.url:
            raise Exception("Login failed - URL does not contain 'home'")

        if get_config().DIGEST_ENABLED:
            get_provider().health_check()
        process_all_articles(context, page, force=force)

        browser.close()
    except Exception as e:
        logger.error(f"Error in main run function: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def _find_articles(page):
    logger.debug("Looking for feed element")
    try:
        page.locator(FEED_SELECTOR).wait_for(state="visible", timeout=FEED_WAIT_MS)
    except PlaywrightTimeoutError as error:
        raise Exception(
            f"Feed element did not load on the Social Schools home page (URL: {page.url})"
        ) from error
    feed = page.query_selector(FEED_SELECTOR)
    if not feed:
        logger.error("Feed element not found")
        raise Exception("Feed element not found")
    logger.debug("Feed element found")
    return feed.query_selector_all(ARTICLE_SELECTOR)


def process_all_articles(context, page, force=False):
    try:
        articles = _find_articles(page)
        if not articles:
            logger.warning("No articles found in feed")
            return
        logger.info(f"Found {len(articles)} article(s) in feed")
        events.tally("run", "articles_seen", len(articles))

        processed_ids = load_processed_articles()
        for article in articles:
            _consider_article(context, article, processed_ids, force)
    except Exception as e:
        logger.error(f"Error in process_all_articles: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def _consider_article(context, article, processed_ids, force):
    article_id = get_article_id(article)
    title = get_article_title(article)
    logger.info(f"Checking article: {title} [{article_id}]")

    if not force and article_id in processed_ids:
        logger.info(f"Article {article_id} already processed, skipping")
        return

    events.tally("run", "articles_new")
    if force:
        logger.info(f"Force mode active: processing article {article_id} without updating state")
    else:
        logger.info(f"Processing new article: {article_id}")

    expand_full_text(article)

    try:
        if not process_article_content(context, article, force=force):
            # Left unmarked deliberately so the next run retries it.
            logger.warning(f"Article {article_id} not fully processed, leaving unmarked")
            return
        events.tally("run", "articles_processed")
        if not force:
            save_processed_article(article_id)
            processed_ids.append(article_id)
    except Exception as e:
        events.tally("run", "articles_failed")
        logger.error(f"Error processing article {article_id}: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        notify_admin(
            "Article processing failed",
            f"Article: {title} [{article_id}]\nLeft unmarked; it will be retried on the next run.",
            exc=e,
        )


def process_article_content(context, article, force=False):
    """Process one Article end to end.

    True only when it was fully handled and every notification was delivered, so
    the caller may mark it processed.
    """
    with Event("article", article_id=get_article_id(article), forced=force) as event:
        with events.as_current("article", event):
            handled = _process_article_content(context, article, event)
        event["outcome"] = "ok" if handled else "incomplete"
        return handled


def _process_article_content(context, article, event):
    try:
        body = read_visible_article_body(article)
    except ValueError as exc:
        logger.warning(f"Skipping article with no readable body: {exc}")
        event["skipped"] = "unreadable_body"
        notify_admin(
            "Article body could not be read",
            "The article markup did not match any known body selector; it stays unmarked for retry.",
            exc=exc,
        )
        return False

    title = get_article_title(article)
    post_date = get_post_date(article)
    digest_enabled = get_config().DIGEST_ENABLED
    event.update(
        title_sha8=sha8(title), title_chars=len(title), body_chars=len(body),
        has_post_date=bool(post_date), mode="digest" if digest_enabled else "translation",
    )

    if not digest_enabled:
        return _deliver_translation(title, body, event)
    return _deliver_digest(context, article, title, body, post_date, event)


def _deliver_translation(title, body, event):
    """Translation mode: no LLM, no attachments, one translation per language."""
    logger.info("Digest disabled — sending translated content directly")
    content = {
        language: (translate(title, dest=language), translate(body, dest=language))
        for language in get_requested_languages()
    }
    event["notification_chars"] = max(len(body) for _, body in content.values())
    send_multilingual_notification(content)
    return True


def _deliver_digest(context, article, title, body, post_date, event):
    pdf_links, docx_links, attachments = collect_attachments(article, context)
    event.update(
        pdf_links=len(pdf_links), docx_links=len(docx_links),
        attachments=len(attachments),
        attachments_failed=sum(1 for a in attachments if a.failed),
        attachment_chars=sum(len(a.text) for a in attachments if not a.failed),
    )

    # One Digest per requested language — never more than recipients asked for.
    languages = get_requested_languages()
    event["languages"] = ",".join(sorted(languages))
    try:
        digests = {language: generate_digest(title, body, attachments, language=language)
                   for language in languages}
    except RuntimeError as e:
        logger.error(f"Digest generation failed: {e}")
        event["skipped"] = "digest_failed"
        send_notification(
            title="Social Schools update",
            body="Could not generate Digest for the latest article. Will retry on next run.",
        )
        raise

    failed_names = [a.filename for a in attachments if a.failed] or None
    content = {
        language: (
            digest.translated_title,
            render_digest_notification(
                digest,
                failed_attachments=failed_names,
                original_title=title,
                post_date=post_date,
            ),
        )
        for language, digest in digests.items()
    }
    record_digest_shape(event, digests, content, title)
    send_multilingual_notification(content)
    return True


def record_digest_shape(event, digests, content, title):
    """What was produced, as counts and flags — never as text (ADR 0008).

    has_footer is here because a deterministic part of the notification once
    stopped appearing and nothing in the system could say when.
    """
    first = next(iter(digests.values()))
    rendered = next(iter(content.values()))[1]
    event.update(
        topics=len(first.topics),
        actions=sum(len(topic.actions) for topic in first.topics),
        bring=sum(len(topic.bring) for topic in first.topics),
        notes=sum(len(topic.notes) for topic in first.topics),
        tldr_chars=len(first.tldr or ""),
        translated_title_chars=len(first.translated_title or ""),
        notification_chars=len(rendered),
        has_footer=title in rendered,
        has_no_action="No action needed" in rendered,
        has_attachment_warning="could not be read" in rendered,
    )
