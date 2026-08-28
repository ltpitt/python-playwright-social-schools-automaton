import os
from unittest.mock import Mock, call, patch

import pytest

from socialschools.models import Attachment, Digest, Topic
from socialschools.pipeline import process_all_articles, process_article_content, run


# =============================================================================
# ONE ARTICLE, END TO END
# =============================================================================


def test_process_article_content(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('socialschools.pipeline.send_multilingual_notification') as mock_notify, \
         patch('socialschools.pipeline.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            topics=[],
        )

        process_article_content(context, article)

        mock_digest.assert_called_once()
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "Short summary\n\nNo action needed\n\n"
                "To find this post in Social Schools, look for: \"Test Content\"",
            ),
        })


def test_process_article_content_error(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Missing content should be skipped gracefully instead of crashing the whole run
    article = Mock()
    article.query_selector.return_value = None

    process_article_content(context, article)


def test_process_article_content_missing_attachments(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content but no attachments
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('socialschools.pipeline.send_multilingual_notification') as mock_notify, \
         patch('socialschools.pipeline.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            topics=[],
        )

        process_article_content(context, article)

        mock_digest.assert_called_once_with("Test Content", "Test Content", [], language="en")
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "Short summary\n\nNo action needed\n\n"
                "To find this post in Social Schools, look for: \"Test Content\"",
            ),
        })


def test_process_article_content_with_pdf_and_docx(mock_playwright):
    """Test process_article_content with both PDF and DOCX attachments"""
    playwright, browser, context, page = mock_playwright

    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Test Title"
    body_element = Mock()
    body_element.inner_text.return_value = "Test Body"

    article.query_selector.side_effect = lambda selector: {
        "span[as='div']": body_element,
        "h3": title_element,
        "a.meta-info": None,
    }[selector]

    # Mock PDF and DOCX links
    pdf_link = Mock()
    docx_link = Mock()
    article.query_selector_all.side_effect = lambda selector: {
        "a[href*='.pdf']": [pdf_link],
        "a[href*='.docx']": [docx_link],
    }.get(selector, [])

    pdf_attachment = Attachment(filename="doc.pdf", url="http://example.com/doc.pdf",
                                filetype="pdf", text="PDF text")
    docx_attachment = Attachment(filename="doc.docx", url="http://example.com/doc.docx",
                                 filetype="docx", text="DOCX text")

    def links_to_attachments(_context, _links, filetype):
        return [pdf_attachment] if filetype == "pdf" else [docx_attachment]

    with patch('socialschools.pipeline.send_multilingual_notification') as mock_notify, \
         patch('socialschools.pipeline.generate_digest') as mock_digest, \
         patch('socialschools.scraping.attachments.process_links',
               side_effect=links_to_attachments) as mock_process_links:

        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="",
            topics=[Topic(heading="", actions=["15 Aug - action"], bring=[], notes=[])],
        )

        process_article_content(context, article)

        # Should process both PDF and DOCX
        assert mock_process_links.call_args_list == [
            call(context, [pdf_link], "pdf"),
            call(context, [docx_link], "docx"),
        ]
        mock_digest.assert_called_once_with(
            "Test Title", "Test Body",
            [pdf_attachment, docx_attachment],
            language="en",
        )
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "\u25b8 15 Aug - action\n\n"
                "To find this post in Social Schools, look for: \"Test Title\"",
            ),
        })


def test_process_article_content_digest_failure(mock_playwright, mock_config):
    """Test that digest failure sends an operational notice and re-raises (leaving article unmarked)"""
    playwright, browser, context, page = mock_playwright

    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('socialschools.pipeline.send_notification') as mock_notify, \
         patch('socialschools.pipeline.generate_digest',
               side_effect=RuntimeError("Copilot CLI returned code 1")):
        with pytest.raises(RuntimeError):
            process_article_content(context, article)

        mock_notify.assert_called_once_with(
            title="Social Schools update",
            body="Could not generate Digest for the latest article. Will retry on next run.",
        )


def test_process_article_content_digest_disabled(mock_playwright, mock_config):
    """Test that DIGEST_ENABLED=false sends translated title+body without Copilot CLI"""
    playwright, browser, context, page = mock_playwright

    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Dutch content"
    article.query_selector_all.return_value = []

    mock_config.DIGEST_ENABLED = False

    with patch('socialschools.pipeline.send_multilingual_notification') as mock_notify, \
         patch('socialschools.pipeline.translate', return_value="Translated") as mock_translate, \
         patch('socialschools.pipeline.generate_digest') as mock_digest:

        process_article_content(context, article)

        mock_digest.assert_not_called()
        assert mock_translate.call_count == 2  # title + body
        mock_notify.assert_called_once_with({"en": ("Translated", "Translated")})


def test_translation_mode_uses_no_llm_provider(mock_playwright, mock_config):
    """DIGEST_ENABLED=false must never build a provider or hit subprocess/HTTP"""
    playwright, browser, context, page = mock_playwright
    mock_config.DIGEST_ENABLED = False

    body_el = Mock()
    body_el.inner_text.return_value = "Dutch body"
    title_el = Mock()
    title_el.inner_text.return_value = "Dutch title"

    def query_selector(selector):
        if selector == "span[as='div']":
            return body_el
        if selector == "h3":
            return title_el
        return None

    article = Mock()
    article.query_selector.side_effect = query_selector

    with patch('socialschools.pipeline.get_provider') as mock_get_provider, \
            patch('socialschools.pipeline.translate', side_effect=lambda t, dest=None: f"EN:{t}"), \
            patch('socialschools.pipeline.send_multilingual_notification') as mock_notify, \
            patch('requests.post') as mock_post, \
            patch('subprocess.run') as mock_run:
        process_article_content(context, article)

    mock_get_provider.assert_not_called()
    mock_post.assert_not_called()
    mock_run.assert_not_called()
    mock_notify.assert_called_once()


def test_process_article_content_returns_false_when_body_unreadable():
    article = Mock()
    article.query_selector.return_value = None
    article.query_selector_all.return_value = []

    with patch('socialschools.pipeline.notify_admin') as mock_admin, \
         patch('socialschools.pipeline.send_notification') as mock_send:
        result = process_article_content(Mock(), article)

    assert result is False
    mock_send.assert_not_called()
    mock_admin.assert_called_once()


# =============================================================================
# WALKING THE FEED
# =============================================================================


def test_process_all_articles_new_article(mock_playwright):
    """Test that a new unseen article is processed and saved"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Test Article Title"

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article]
    article.get_attribute.return_value = "test_article_id"
    article.query_selector.side_effect = lambda selector: {
        "h3": title_element,
    }.get(selector)

    with patch('socialschools.pipeline.load_processed_articles',
               return_value=[]) as mock_load, \
         patch('socialschools.pipeline.save_processed_article') as mock_save, \
         patch('socialschools.pipeline.expand_full_text') as mock_expand, \
         patch('socialschools.pipeline.process_article_content') as mock_process:

        process_all_articles(context, page)

        page.locator.assert_called_once_with("div[role='feed']")
        page.locator.return_value.wait_for.assert_called_once_with(
            state="visible", timeout=60000
        )

        mock_load.assert_called()
        mock_expand.assert_called_once_with(article)
        mock_process.assert_called_once_with(context, article, force=False)
        mock_save.assert_called_once_with("test_article_id")


def test_process_all_articles_feed_not_found(mock_playwright):
    """Test process_all_articles raises when feed element is not found"""
    playwright, browser, context, page = mock_playwright
    page.query_selector.return_value = None

    with pytest.raises(Exception, match="Feed element not found"):
        process_all_articles(context, page)


def test_process_all_articles_no_articles(mock_playwright):
    """Test process_all_articles returns quietly when feed is empty"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    feed.query_selector_all.return_value = []
    page.query_selector.return_value = feed

    with patch('socialschools.pipeline.process_article_content') as mock_process:
        process_all_articles(context, page)
        mock_process.assert_not_called()


def test_process_all_articles_skips_seen(mock_playwright):
    """Test process_all_articles skips already-processed articles"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Test Article Title"
    article.query_selector.return_value = title_element
    article.get_attribute.return_value = "processed_article_id"

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article]

    with patch('socialschools.pipeline.load_processed_articles',
               return_value=["processed_article_id"]), \
         patch('socialschools.pipeline.process_article_content') as mock_process:

        process_all_articles(context, page)

        mock_process.assert_not_called()


def test_process_all_articles_continues_on_error(mock_playwright):
    """Test that a per-article error doesn't stop processing subsequent articles"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article1, article2 = Mock(), Mock()
    title_el = Mock()
    title_el.inner_text.return_value = "Title"
    article1.get_attribute.return_value = "article_1"
    article2.get_attribute.return_value = "article_2"
    article1.query_selector.return_value = title_el
    article2.query_selector.return_value = title_el

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article1, article2]

    with patch('socialschools.pipeline.load_processed_articles', return_value=[]), \
         patch('socialschools.pipeline.save_processed_article') as mock_save, \
         patch('socialschools.pipeline.expand_full_text'), \
         patch('socialschools.pipeline.process_article_content',
               side_effect=[RuntimeError("Digest failed"), True]) as mock_process:

        process_all_articles(context, page)

        assert mock_process.call_count == 2
        mock_save.assert_called_once_with("article_2")  # article_1 failed, not saved


def test_process_all_articles_skips_save_when_not_fully_successful(mock_playwright):
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_el = Mock()
    title_el.inner_text.return_value = "Title"
    article.get_attribute.return_value = "article_1"
    article.query_selector.return_value = title_el

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article]

    with patch('socialschools.pipeline.load_processed_articles', return_value=[]), \
         patch('socialschools.pipeline.save_processed_article') as mock_save, \
         patch('socialschools.pipeline.expand_full_text'), \
         patch('socialschools.pipeline.process_article_content', return_value=False):

        process_all_articles(context, page)

    mock_save.assert_not_called()


def test_process_all_articles_alerts_admin_on_article_failure(mock_playwright):
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_el = Mock()
    title_el.inner_text.return_value = "Title"
    article.get_attribute.return_value = "article_1"
    article.query_selector.return_value = title_el

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article]

    with patch('socialschools.pipeline.load_processed_articles', return_value=[]), \
         patch('socialschools.pipeline.save_processed_article') as mock_save, \
         patch('socialschools.pipeline.expand_full_text'), \
         patch('socialschools.pipeline.notify_admin') as mock_admin, \
         patch('socialschools.pipeline.process_article_content',
               side_effect=RuntimeError("Digest failed")):

        process_all_articles(context, page)

    mock_save.assert_not_called()
    mock_admin.assert_called_once()


def test_article_id_generation_fallback(mock_playwright):
    """Test article ID generation when no data-id or id attribute exists"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Fallback Title"
    time_element = Mock()
    time_element.get_attribute.return_value = "2023-12-01T10:00:00Z"

    page.query_selector.return_value = feed
    feed.query_selector_all.return_value = [article]
    article.get_attribute.return_value = None  # No ID attributes
    article.query_selector.side_effect = lambda selector: {
        "h3": title_element,
        "time": time_element,
    }.get(selector)

    with patch('socialschools.pipeline.load_processed_articles', return_value=[]), \
         patch('socialschools.pipeline.save_processed_article',
               return_value=True) as mock_save, \
         patch('socialschools.pipeline.expand_full_text'), \
         patch('socialschools.pipeline.process_article_content'):

        process_all_articles(context, page)

        expected_id = "Fallback Title_2023-12-01T10:00:00Z"
        mock_save.assert_called_once_with(expected_id)


# =============================================================================
# THE WHOLE RUN
# =============================================================================


def test_run_function_success(mock_playwright):
    """Test successful run function execution"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/home/dashboard"
    expected_browser = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or "/tmp/test-chrome"

    with patch('socialschools.scraping.browser.resolve_browser_executable_path',
               return_value=expected_browser), \
         patch('socialschools.pipeline.login_to_website') as mock_login, \
         patch('socialschools.pipeline.process_all_articles') as mock_process, \
         patch('socialschools.llm.copilot.check_copilot_available'):

        run(playwright)

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            executable_path=expected_browser
        )
        browser.new_context.assert_called_once()
        context.new_page.assert_called_once()
        mock_login.assert_called_once_with(page)
        mock_process.assert_called_once_with(context, page, force=False)
        browser.close.assert_called_once()


def test_run_function_login_failed(mock_playwright):
    """Test run function when login fails"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/login"

    with patch('socialschools.pipeline.login_to_website'):
        with pytest.raises(Exception,
                           match="Login failed - URL does not contain 'home'"):
            run(playwright)
