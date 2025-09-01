import pytest
import os
import sys
from unittest.mock import Mock, patch, mock_open

# Add the current directory to Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import after path modification to avoid import errors
from get_social_schools_news import (  # noqa: E402
    load_processed_articles,
    save_processed_article,
    translate,
    send_notification,
    process_article_content,
    Config,
    load_config,
    get_config,
    download_pdf,
    extract_text,
    process_pdf_links,
    extract_text_from_docx,
    process_docx_links,
    run,
    login_to_website,
    process_first_article,
    expand_full_text
)


@pytest.fixture(autouse=True)
def mock_config():
    """Automatically mock the config for all tests"""
    test_config = Config(
        SCRAPED_WEBSITE_USER="test_user@example.com",
        SCRAPED_WEBSITE_PASSWORD="test_password",
        PUSHBULLET_API_KEY="test_api_key",
        TRANSLATION_LANGUAGE="en"
    )
    with patch('get_social_schools_news.load_config',
               return_value=test_config):
        yield test_config


@pytest.fixture
def mock_playwright():
    playwright = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()

    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page

    return playwright, browser, context, page


def test_load_processed_articles(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE',
               str(tmp_path / 'processed.json')):
        # Test empty file
        assert load_processed_articles() == []

        # Test with existing articles
        with open(tmp_path / 'processed.json', 'w') as f:
            f.write('["article1", "article2"]')
        assert load_processed_articles() == ["article1", "article2"]


def test_save_processed_article(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE',
               str(tmp_path / 'processed.json')):
        # Test new article
        assert save_processed_article("article1") is True
        assert load_processed_articles() == ["article1"]

        # Test duplicate article
        assert save_processed_article("article1") is False


def test_translate(mock_config):
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.return_value = "Translated text"
        result = translate("Original text")
        assert result == "Translated text"
        mock_translate.assert_called_once()


def test_send_notification(mock_config):
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", "test_key")
        mock_post.assert_called_once()


def test_process_article_content(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate') as mock_translate:
        mock_translate.return_value = "Translated Content"

        process_article_content(playwright, browser, context, article)

        # Verify notifications were sent
        assert mock_notify.call_count == 2
        assert mock_translate.call_count == 2


def test_load_processed_articles_error(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE',
               str(tmp_path / 'processed.json')):
        # Test invalid JSON file
        with open(tmp_path / 'processed.json', 'w') as f:
            f.write('invalid json')
        assert load_processed_articles() == []


def test_save_processed_article_error(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE',
               str(tmp_path / 'processed.json')):
        # Test file permission error
        with patch('builtins.open', side_effect=PermissionError):
            assert save_processed_article("article1") is False


def test_translate_error(mock_config):
    translate_side_effect = Exception("Translation failed")
    with patch('deep_translator.GoogleTranslator.translate',
               side_effect=translate_side_effect):
        with pytest.raises(Exception):
            translate("Original text")


def test_send_notification_error(mock_config):
    with patch('requests.post', side_effect=Exception("Network error")):
        # Should not raise exception
        send_notification("Test Title", "Test Body", "test_key")


def test_process_article_content_error(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with missing content
    article = Mock()
    article.query_selector.return_value = None

    with pytest.raises(AttributeError):
        process_article_content(playwright, browser, context, article)


def test_process_article_content_missing_attachments(mock_playwright,
                                                     mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content but no attachments
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate') as mock_translate:
        mock_translate.return_value = "Translated Content"

        process_article_content(playwright, browser, context, article)

        # Verify only article content notifications were sent
        assert mock_notify.call_count == 2
        assert mock_translate.call_count == 2


# =============================================================================
# CONFIG HANDLING TESTS
# =============================================================================


def test_load_config_with_config_ini(tmp_path):
    """Test load_config with config.ini file"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
            'PUSHBULLET_API_KEY': 'api_key_123'
        }[key])
        mock_default_section.get = Mock(return_value='it')

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.SCRAPED_WEBSITE_USER == 'user@example.com'
        assert result.SCRAPED_WEBSITE_PASSWORD == 'password123'
        assert result.PUSHBULLET_API_KEY == 'api_key_123'
        assert result.TRANSLATION_LANGUAGE == 'it'


def test_load_config_fallback_to_example(tmp_path):
    """Test load_config falls back to config.example.ini"""
    with patch('os.path.exists', return_value=False):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'example@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'example_pass',
            'PUSHBULLET_API_KEY': 'example_key'
        }[key])
        mock_default_section.get = Mock(return_value='en')

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.SCRAPED_WEBSITE_USER == 'example@example.com'
        assert result.TRANSLATION_LANGUAGE == 'en'


def test_get_config_caching():
    """Test that get_config caches the configuration"""
    with patch('get_social_schools_news.load_config') as mock_load:
        mock_config = Config(
            SCRAPED_WEBSITE_USER="cached@example.com",
            SCRAPED_WEBSITE_PASSWORD="cached_pass",
            PUSHBULLET_API_KEY="cached_key"
        )
        mock_load.return_value = mock_config

        # Reset global config
        import get_social_schools_news
        get_social_schools_news.config = None

        # First call should load config
        result1 = get_config()
        assert mock_load.call_count == 1

        # Second call should use cached config
        result2 = get_config()
        assert mock_load.call_count == 1  # No additional calls
        assert result1 is result2


# =============================================================================
# PDF PROCESSING TESTS
# =============================================================================


def test_download_pdf_success():
    """Test successful PDF download"""
    mock_pdf_content = b"fake pdf content"

    with patch('pycurl.Curl') as mock_curl_class:
        mock_curl = Mock()
        mock_curl_class.return_value = mock_curl

        with patch('builtins.open', mock_open()) as mock_file, \
             patch('get_social_schools_news.BytesIO') as mock_bytesio:
            mock_buffer = Mock()
            mock_buffer.getvalue.return_value = mock_pdf_content
            mock_bytesio.return_value = mock_buffer

            download_pdf("http://example.com/test.pdf", "/tmp/test.pdf")

            mock_curl.setopt.assert_any_call(mock_curl.URL,
                                             "http://example.com/test.pdf")
            mock_curl.setopt.assert_any_call(mock_curl.WRITEDATA, mock_buffer)
            mock_curl.perform.assert_called_once()
            mock_curl.close.assert_called_once()
            mock_file.assert_called_once_with("/tmp/test.pdf", "wb")


def test_extract_text_from_pdf():
    """Test text extraction from PDF"""
    mock_text = "Extracted PDF text content"

    with patch('fitz.open') as mock_fitz_open:
        mock_doc = Mock()
        mock_page = Mock()
        mock_page.get_text.return_value = mock_text
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))
        mock_fitz_open.return_value = mock_doc

        result = extract_text("/tmp/test.pdf")

        assert result == mock_text
        mock_fitz_open.assert_called_once_with("/tmp/test.pdf")
        mock_page.get_text.assert_called_once()


def test_process_pdf_links():
    """Test processing PDF links with notifications"""
    playwright, browser, context = Mock(), Mock(), Mock()

    # Mock PDF links
    mock_link1 = Mock()
    mock_link1.get_attribute.return_value = "http://example.com/test1.pdf"
    mock_link2 = Mock()
    mock_link2.get_attribute.return_value = "http://example.com/test2.pdf"
    pdf_links = [mock_link1, mock_link2]

    with patch('get_social_schools_news.download_pdf') as mock_download, \
         patch('get_social_schools_news.extract_text') as mock_extract, \
         patch('get_social_schools_news.translate') as mock_translate, \
         patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('tempfile.TemporaryDirectory'):

        mock_extract.return_value = "PDF content"
        mock_translate.return_value = "Translated PDF content"

        process_pdf_links(playwright, browser, context, pdf_links)

        # Should download and process both PDFs
        assert mock_download.call_count == 2
        assert mock_extract.call_count == 2
        assert mock_translate.call_count == 2
        assert mock_notify.call_count == 4  # 2 original + 2 translated


# =============================================================================
# DOCX PROCESSING TESTS
# =============================================================================


def test_extract_text_from_docx():
    """Test text extraction from Word document"""
    with patch('get_social_schools_news.Document') as mock_document:
        mock_doc = Mock()
        mock_paragraph1 = Mock()
        mock_paragraph1.text = "First paragraph"
        mock_paragraph2 = Mock()
        mock_paragraph2.text = "Second paragraph"
        mock_doc.paragraphs = [mock_paragraph1, mock_paragraph2]
        mock_document.return_value = mock_doc

        result = extract_text_from_docx("/tmp/test.docx")

        expected = "First paragraph\nSecond paragraph\n"
        assert result == expected
        mock_document.assert_called_once_with("/tmp/test.docx")


def test_process_docx_links():
    """Test processing DOCX links with notifications"""
    playwright, browser, context = Mock(), Mock(), Mock()

    # Mock DOCX links
    mock_link = Mock()
    mock_link.get_attribute.return_value = "http://example.com/test.docx"
    docx_links = [mock_link]

    with patch('get_social_schools_news.download_pdf') as mock_download, \
         patch('get_social_schools_news.extract_text_from_docx') as \
         mock_extract, \
         patch('get_social_schools_news.translate') as mock_translate, \
         patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('tempfile.TemporaryDirectory'):

        mock_extract.return_value = "DOCX content"
        mock_translate.return_value = "Translated DOCX content"

        process_docx_links(playwright, browser, context, docx_links)

        mock_download.assert_called_once()
        mock_extract.assert_called_once()
        mock_translate.assert_called_once()
        assert mock_notify.call_count == 2  # Original + translated


# =============================================================================
# BROWSER AUTOMATION TESTS
# =============================================================================


def test_login_to_website_success(mock_playwright):
    """Test successful website login"""
    playwright, browser, context, page = mock_playwright

    # Mock successful login flow
    username_field = Mock()
    username_field.is_visible.return_value = True
    password_field = Mock()
    password_field.is_visible.return_value = True

    page.locator.side_effect = lambda selector: {
        "#username": username_field,
        "#Password": password_field
    }[selector]

    with patch('get_social_schools_news.get_config') as mock_get_config:
        mock_config = Config(
            SCRAPED_WEBSITE_USER="test@example.com",
            SCRAPED_WEBSITE_PASSWORD="testpass",
            PUSHBULLET_API_KEY="testkey"
        )
        mock_get_config.return_value = mock_config

        login_to_website(page)

        page.goto.assert_called_once_with("https://app.socialschools.eu/home")
        page.wait_for_load_state.assert_called()
        page.fill.assert_any_call("#username", "test@example.com")
        page.fill.assert_any_call("#Password", "testpass")
        page.press.assert_called_once_with("#Password", "Enter")


def test_login_to_website_username_field_not_found(mock_playwright):
    """Test login failure when username field is not found"""
    playwright, browser, context, page = mock_playwright

    username_field = Mock()
    username_field.is_visible.return_value = False
    page.locator.return_value = username_field

    with pytest.raises(Exception, match="Username field not found"):
        login_to_website(page)


def test_login_to_website_password_field_not_found(mock_playwright):
    """Test login failure when password field is not found"""
    playwright, browser, context, page = mock_playwright

    username_field = Mock()
    username_field.is_visible.return_value = True
    password_field = Mock()
    password_field.is_visible.return_value = False

    page.locator.side_effect = lambda selector: {
        "#username": username_field,
        "#Password": password_field
    }[selector]

    with pytest.raises(Exception, match="Password field not found"):
        login_to_website(page)


def test_expand_full_text_with_button():
    """Test expanding full text when 'Meer weergeven' button exists"""
    article = Mock()
    more_button = Mock()
    article.query_selector.return_value = more_button

    expand_full_text(article)

    article.query_selector.assert_called_once_with(
        "button:has-text('Meer weergeven')"
    )
    more_button.click.assert_called_once()
    article.wait_for_selector.assert_called_once_with("span[as='div']")


def test_expand_full_text_no_button():
    """Test expanding full text when no 'Meer weergeven' button exists"""
    article = Mock()
    article.query_selector.return_value = None

    expand_full_text(article)

    article.query_selector.assert_called_once()
    article.wait_for_selector.assert_called_once_with("span[as='div']")


def test_process_first_article_success(mock_playwright):
    """Test successful processing of first article"""
    playwright, browser, context, page = mock_playwright

    # Mock feed and article elements
    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Test Article Title"
    time_element = Mock()
    time_element.get_attribute.return_value = "2023-12-01T10:00:00Z"

    feed.query_selector.return_value = article
    article.query_selector.side_effect = lambda selector: {
        "h3": title_element,
        "time": time_element
    }.get(selector)
    article.get_attribute.return_value = "test_article_id"

    page.query_selector.return_value = feed

    with patch('get_social_schools_news.save_processed_article',
               return_value=True) as mock_save, \
         patch('get_social_schools_news.expand_full_text') as mock_expand, \
         patch('get_social_schools_news.process_article_content') as \
         mock_process:

        process_first_article(playwright, browser, context, page)

        mock_save.assert_called_once_with("test_article_id")
        mock_expand.assert_called_once_with(article)
        mock_process.assert_called_once_with(playwright, browser, context,
                                             article)


def test_process_first_article_feed_not_found(mock_playwright):
    """Test process_first_article when feed element is not found"""
    playwright, browser, context, page = mock_playwright
    page.query_selector.return_value = None

    with pytest.raises(Exception, match="Feed element not found"):
        process_first_article(playwright, browser, context, page)


def test_process_first_article_no_article_found(mock_playwright):
    """Test process_first_article when no article is found in feed"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    feed.query_selector.return_value = None
    page.query_selector.return_value = feed

    with pytest.raises(Exception, match="No article found"):
        process_first_article(playwright, browser, context, page)


def test_process_first_article_already_processed(mock_playwright):
    """Test process_first_article when article is already processed"""
    playwright, browser, context, page = mock_playwright

    # Mock feed and article elements
    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Test Article Title"

    feed.query_selector.return_value = article
    article.query_selector.return_value = title_element
    article.get_attribute.return_value = "processed_article_id"

    page.query_selector.return_value = feed

    with patch('get_social_schools_news.save_processed_article',
               return_value=False) as mock_save:

        process_first_article(playwright, browser, context, page)

        mock_save.assert_called_once_with("processed_article_id")
        # Should return early without processing


def test_run_function_success(mock_playwright):
    """Test successful run function execution"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/home/dashboard"

    with patch('get_social_schools_news.login_to_website') as mock_login, \
         patch('get_social_schools_news.process_first_article') as \
         mock_process:

        run(playwright)

        playwright.chromium.launch.assert_called_once_with(headless=True)
        browser.new_context.assert_called_once()
        context.new_page.assert_called_once()
        mock_login.assert_called_once_with(page)
        mock_process.assert_called_once_with(playwright, browser, context,
                                             page)
        browser.close.assert_called_once()


def test_run_function_login_failed(mock_playwright):
    """Test run function when login fails"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/login"

    with patch('get_social_schools_news.login_to_website'):
        with pytest.raises(Exception,
                           match="Login failed - URL does not contain 'home'"):
            run(playwright)


# =============================================================================
# ADDITIONAL EDGE CASE TESTS
# =============================================================================


@pytest.mark.parametrize("language,expected", [
    ("nl", "en"),  # Default destination
    ("en", "it"),  # Custom destination
    ("fr", "es"),  # Different source and destination
])
def test_translate_with_different_languages(mock_config, language,
                                            expected):
    """Test translation with different source and destination languages"""
    with patch('get_social_schools_news.GoogleTranslator') as \
            mock_translator_class:
        mock_translator = Mock()
        mock_translator.translate.return_value = f"translated to {expected}"
        mock_translator_class.return_value = mock_translator

        result = translate("test text", src=language, dest=expected)

        mock_translator_class.assert_called_once_with(source=language,
                                                      target=expected)
        assert result == f"translated to {expected}"


def test_translate_with_chunks(mock_config):
    """Test translation with text that requires chunking"""
    long_text = "a" * 10000  # Text longer than default chunk size

    with patch('get_social_schools_news.GoogleTranslator') as \
            mock_translator_class:
        mock_translator = Mock()
        mock_translator.translate.side_effect = \
            lambda chunk: f"t({len(chunk)})"
        mock_translator_class.return_value = mock_translator

        result = translate(long_text, chunk_size=4900)

        # Should be called 3 times for the chunks
        assert mock_translator.translate.call_count == 3
        assert result == "t(4900) t(4900) t(200)"


def test_send_notification_with_custom_api_key():
    """Test send_notification with custom API key"""
    with patch('requests.post') as mock_post:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        send_notification("Test", "Body", "custom_api_key")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        headers = call_args[1]['headers']
        assert headers['Authorization'] == "Bearer custom_api_key"


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
        "h3": title_element
    }[selector]

    # Mock PDF and DOCX links
    pdf_link = Mock()
    docx_link = Mock()
    article.query_selector_all.side_effect = lambda selector: {
        "a[href*='.pdf']": [pdf_link],
        "a[href*='.docx']": [docx_link]
    }[selector]

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate') as mock_translate, \
         patch('get_social_schools_news.process_pdf_links') as mock_pdf, \
         patch('get_social_schools_news.process_docx_links') as mock_docx:

        mock_translate.return_value = "Translated"

        process_article_content(playwright, browser, context, article)

        # Should send article notifications
        assert mock_notify.call_count == 2
        # Should process both PDF and DOCX
        mock_pdf.assert_called_once_with(playwright, browser, context,
                                         [pdf_link])
        mock_docx.assert_called_once_with(playwright, browser, context,
                                          [docx_link])


# =============================================================================
# ERROR HANDLING AND ROBUSTNESS TESTS
# =============================================================================


def test_article_id_generation_fallback(mock_playwright):
    """Test article ID generation when no data-id or id attribute exists"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    article = Mock()
    title_element = Mock()
    title_element.inner_text.return_value = "Fallback Title"
    time_element = Mock()
    time_element.get_attribute.return_value = "2023-12-01T10:00:00Z"

    feed.query_selector.return_value = article
    article.query_selector.side_effect = lambda selector: {
        "h3": title_element,
        "time": time_element
    }.get(selector)
    article.get_attribute.return_value = None  # No ID attributes

    page.query_selector.return_value = feed

    with patch('get_social_schools_news.save_processed_article',
               return_value=True) as mock_save, \
         patch('get_social_schools_news.expand_full_text'), \
         patch('get_social_schools_news.process_article_content'):

        process_first_article(playwright, browser, context, page)

        # Should generate ID from title and timestamp
        expected_id = "Fallback Title_2023-12-01T10:00:00Z"
        mock_save.assert_called_once_with(expected_id)


def test_config_missing_translation_language():
    """Test config loading with missing TRANSLATION_LANGUAGE"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
            'PUSHBULLET_API_KEY': 'api_key_123'
        }[key])
        mock_default_section.get = Mock(return_value='en')

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.TRANSLATION_LANGUAGE == 'en'
