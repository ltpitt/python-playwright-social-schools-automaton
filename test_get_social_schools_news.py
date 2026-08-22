import json
import pytest
import os
import sys
from datetime import date
from unittest.mock import Mock, patch, mock_open
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Add the current directory to Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import after path modification to avoid import errors
from get_social_schools_news import (  # noqa: E402
    load_processed_articles,
    save_processed_article,
    translate,
    send_notification,
    generate_digest,
    render_digest_notification,
    process_article_content,
    Config,
    Digest,
    Topic,
    Attachment,
    load_config,
    get_config,
    download_pdf,
    extract_text,
    process_pdf_links,
    extract_text_from_docx,
    process_docx_links,
    run,
    login_to_website,
    process_all_articles,
    expand_full_text,
    _check_copilot_available,
    _get_article_id,
    _get_post_date,
    _COPILOT_TOOL_FREE_ARGS,
    _dict_to_digest,
    _parse_api_keys,
    _parse_recipients,
    Recipient,
    get_requested_languages,
    send_multilingual_notification,
    _extract_action_hints,
    notify_admin,
    get_provider,
    CopilotCliProvider,
    OpenAICompatibleProvider,
)
import evaluate_digests  # noqa: E402


@pytest.fixture(autouse=True)
def mock_config():
    """Automatically mock the config for all tests"""
    test_config = Config(
        SCRAPED_WEBSITE_USER="test_user@example.com",
        SCRAPED_WEBSITE_PASSWORD="test_password",
        PUSHBULLET_API_KEYS="Test:test_api_key",
        TRANSLATION_LANGUAGE="en",
        DIGEST_ENABLED=True,
    )
    import get_social_schools_news
    get_social_schools_news.config = None  # reset cached config before each test
    get_social_schools_news._translation_cache.clear()
    with patch('get_social_schools_news.load_config',
               return_value=test_config):
        yield test_config
    get_social_schools_news.config = None  # clean up after test


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
        send_notification("Test Title", "Test Body", "Test:test_key")
        mock_post.assert_called_once()


def test_send_notification_with_single_key_posts_once(mock_config):
    """Test that a single 'name:token' entry results in exactly one push"""
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", "Test:test_key")
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test_key"


def test_send_notification_with_multiple_keys_pushes_to_each_recipient():
    """Test that the same notification is pushed individually to each named recipient"""
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body", api_keys={"Test": "test_key", "Partner": "partner_key"})
        assert mock_post.call_count == 2
        sent_keys = [call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list]
        assert sent_keys == ["Bearer test_key", "Bearer partner_key"]


def test_send_notification_uses_configured_api_keys(mock_config):
    """Test that send_notification falls back to Config.PUSHBULLET_API_KEYS when not passed explicitly"""
    mock_config.PUSHBULLET_API_KEYS = "Test:test_key,Partner:partner_key,Grandma:another_key"
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        send_notification("Test Title", "Test Body")
        assert mock_post.call_count == 3
        sent_keys = [call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list]
        assert sent_keys == ["Bearer test_key", "Bearer partner_key", "Bearer another_key"]


def test_parse_api_keys_splits_and_strips():
    assert _parse_api_keys("Partner: key1 , Grandma:key2") == {"Partner": "key1", "Grandma": "key2"}


def test_parse_api_keys_rejects_entry_missing_colon():
    with pytest.raises(ValueError):
        _parse_api_keys("just_a_key_no_name")


def test_parse_api_keys_rejects_entry_missing_name():
    with pytest.raises(ValueError):
        _parse_api_keys(":key_without_a_name")


def test_send_notification_raises_on_http_error():
    """Test send_notification propagates HTTP errors so articles stay unmarked for retry"""
    import requests as req_lib
    with patch('requests.post') as mock_post:
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = req_lib.exceptions.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_response
        with pytest.raises(req_lib.exceptions.HTTPError):
            send_notification("Test", "Body", "Test:bad_key")


def test_send_notification_sends_email_when_configured(mock_config):
    """Email is sent (in addition to Pushbullet) when EMAIL_RECIPIENTS is set"""
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com,Partner:partner@example.com"
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        mock_post.return_value.status_code = 200
        server = mock_smtp.return_value.__enter__.return_value
        send_notification("Test Title", "Test Body")
        server.login.assert_called_once_with("sender@gmail.com", "app_password")
        assert server.send_message.call_count == 2
        sent_to = [call.args[0]["To"] for call in server.send_message.call_args_list]
        assert sent_to == ["you@example.com", "partner@example.com"]


def test_send_notification_email_only_skips_pushbullet(mock_config):
    """With no Pushbullet keys but email configured, only email is sent"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com"
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        send_notification("Test Title", "Test Body")
        mock_post.assert_not_called()
        server = mock_smtp.return_value.__enter__.return_value
        server.send_message.assert_called_once()


def test_send_notification_no_channels_is_noop(mock_config):
    """With neither Pushbullet nor email configured, nothing is sent"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_RECIPIENTS = ""
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        send_notification("Test Title", "Test Body")
        mock_post.assert_not_called()
        mock_smtp.assert_not_called()


def test_send_notification_email_missing_sender_raises(mock_config):
    """EMAIL_RECIPIENTS set but EMAIL_SENDER/EMAIL_APP_PASSWORD empty raises for retry"""
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_SENDER = ""
    mock_config.EMAIL_APP_PASSWORD = ""
    mock_config.EMAIL_RECIPIENTS = "You:you@example.com"
    with patch('smtplib.SMTP_SSL') as mock_smtp:
        with pytest.raises(ValueError):
            send_notification("Test Title", "Test Body")
        mock_smtp.assert_not_called()


def test_parse_api_keys_parses_email_recipients():
    assert _parse_api_keys("You:you@example.com,Partner:p@example.com",
                           field_name="EMAIL_RECIPIENTS") == {
        "You": "you@example.com", "Partner": "p@example.com"}


def test_parse_recipients_defaults_to_translation_language(mock_config):
    """Entries without a ':language' suffix fall back to TRANSLATION_LANGUAGE"""
    mock_config.TRANSLATION_LANGUAGE = "en"
    parsed = _parse_recipients("Davide:token1,Daniela:token2")
    assert parsed["Davide"].value == "token1"
    assert parsed["Davide"].language == "en"
    assert parsed["Daniela"].language == "en"


def test_parse_recipients_honors_per_recipient_language(mock_config):
    parsed = _parse_recipients("Davide:token1:it,Daniela:token2:en")
    assert parsed["Davide"] == Recipient(value="token1", language="it")
    assert parsed["Daniela"] == Recipient(value="token2", language="en")


def test_parse_recipients_rejects_empty_language():
    with pytest.raises(ValueError):
        _parse_recipients("Davide:token1:")


def test_parse_recipients_rejects_too_many_colons():
    with pytest.raises(ValueError):
        _parse_recipients("Davide:token1:it:extra")


def test_get_requested_languages_combines_pushbullet_and_email(mock_config):
    mock_config.PUSHBULLET_API_KEYS = "Davide:token1:it"
    mock_config.EMAIL_RECIPIENTS = "Daniela:d@example.com:en"
    assert get_requested_languages() == {"it", "en"}


def test_get_requested_languages_falls_back_to_translation_language(mock_config):
    mock_config.PUSHBULLET_API_KEYS = ""
    mock_config.EMAIL_RECIPIENTS = ""
    mock_config.TRANSLATION_LANGUAGE = "fr"
    assert get_requested_languages() == {"fr"}


def test_send_multilingual_notification_routes_each_recipient_to_its_language(mock_config):
    """Each recipient only receives the content generated for their own language"""
    mock_config.PUSHBULLET_API_KEYS = "Davide:token_it:it,Daniela:token_en:en"
    mock_config.EMAIL_SENDER = "sender@gmail.com"
    mock_config.EMAIL_APP_PASSWORD = "app_password"
    mock_config.EMAIL_RECIPIENTS = "Mamma:mamma@example.com:it"

    content = {
        "it": ("Titolo", "Corpo"),
        "en": ("Title", "Body"),
    }
    with patch('requests.post') as mock_post, \
            patch('smtplib.SMTP_SSL') as mock_smtp:
        mock_post.return_value.status_code = 200
        send_multilingual_notification(content)

        pushed = {
            call.kwargs["headers"]["Authorization"]: json.loads(call.kwargs["data"])
            for call in mock_post.call_args_list
        }
        assert pushed["Bearer token_it"]["title"] == "Titolo"
        assert pushed["Bearer token_en"]["title"] == "Title"

        server = mock_smtp.return_value.__enter__.return_value
        server.send_message.assert_called_once()
        sent_message = server.send_message.call_args.args[0]
        assert sent_message["Subject"] == "Titolo"
        assert sent_message["To"] == "mamma@example.com"


def test_send_multilingual_notification_skips_language_without_content(mock_config):
    """A configured language missing from content_by_language is skipped, not sent empty"""
    mock_config.PUSHBULLET_API_KEYS = "Davide:token_it:it"
    with patch('requests.post') as mock_post:
        send_multilingual_notification({})
        mock_post.assert_not_called()


def test_translate_caches_identical_text_and_language(mock_config):
    """Repeated translate() calls for the same text+language reuse the cached result"""
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.return_value = "Vertaald"
        first = translate("Original text", dest="nl")
        second = translate("Original text", dest="nl")
        assert first == second == "Vertaald"
        mock_translate.assert_called_once()


def test_translate_does_not_reuse_cache_across_languages(mock_config):
    """The same text translated into a different language triggers a fresh call"""
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.side_effect = ["Vertaald", "Translated"]
        translate("Original text", dest="nl")
        translate("Original text", dest="en")
        assert mock_translate.call_count == 2


def test_process_article_content(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_multilingual_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            topics=[],
        )

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_called_once()
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "Short summary\n\nNo action needed\n\n"
                "To find this post in Social Schools, look for: \"Test Content\"",
            ),
        })


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
    """Test send_notification propagates network errors for retry-on-next-run"""
    with patch('requests.post', side_effect=Exception("Network error")):
        with pytest.raises(Exception, match="Network error"):
            send_notification("Test Title", "Test Body", "Test:test_key")


def test_process_article_content_error(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Missing content should be skipped gracefully instead of crashing the whole run
    article = Mock()
    article.query_selector.return_value = None

    process_article_content(playwright, browser, context, article)


def test_process_article_content_missing_attachments(mock_playwright,
                                                     mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content but no attachments
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_multilingual_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            topics=[],
        )

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_called_once_with("Test Content", "Test Content", [], language="en")
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "Short summary\n\nNo action needed\n\n"
                "To find this post in Social Schools, look for: \"Test Content\"",
            ),
        })


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
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: {
                'PUSHBULLET_API_KEYS': 'Test:api_key_123',
                'TRANSLATION_LANGUAGE': 'it',
            }.get(key, default))

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.SCRAPED_WEBSITE_USER == 'user@example.com'
        assert result.SCRAPED_WEBSITE_PASSWORD == 'password123'
        assert result.PUSHBULLET_API_KEYS == 'Test:api_key_123'
        assert result.TRANSLATION_LANGUAGE == 'it'


def test_load_config_fallback_to_example(tmp_path):
    """Test load_config falls back to config.example.ini"""
    with patch('os.path.exists', return_value=False):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'example@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'example_pass',
            'PUSHBULLET_API_KEYS': 'Test:example_key'
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: {'TRANSLATION_LANGUAGE': 'en'}.get(key, default))

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
            PUSHBULLET_API_KEYS="Test:cached_key"
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
# DIGEST GENERATION TESTS
# =============================================================================


def test_generate_digest(mock_config):
    """Test Digest generation via Copilot CLI subprocess call returns dict"""
    import subprocess
    digest_data = {
        "translated_title": "School Trip",
        "tldr": "Children need gym shoes",
        "topics": [{
            "heading": "School trip",
            "actions": ["15 Aug - bring gym shoes"],
            "bring": [],
            "notes": ["16 Aug - school closed"],
        }],
    }
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(digest_data)

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = generate_digest("School Trip", "Body text", [])

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "copilot"
        assert "-p" in cmd
        prompt_idx = cmd.index("-p") + 1
        assert "School Trip" in cmd[prompt_idx]
        assert "Body text" in cmd[prompt_idx]
        assert "--no-color" in cmd
        assert isinstance(result, Digest)
        assert result.translated_title == "School Trip"
        assert result.topics[0].actions == ["15 Aug - bring gym shoes"]


def test_generate_digest_with_attachments(mock_config):
    """Test Digest generation includes attachment text in prompt"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Form Required",
        "tldr": "A form must be returned",
        "topics": [{"heading": "Form", "actions": ["15 Aug - sign and return the form"],
                    "bring": [], "notes": []}],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [Attachment(
            filename="form.pdf", url="http://example.com/form.pdf",
            filetype="pdf", text="Sign and return by 15 Aug",
        )])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "form.pdf" in prompt
        assert "Sign and return by 15 Aug" in prompt


def test_generate_digest_cli_not_found(mock_config):
    """Test generate_digest raises RuntimeError when copilot CLI is missing"""
    with patch('subprocess.run', side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Copilot CLI not found"):
            generate_digest("Title", "Body", [])


def test_generate_digest_cli_failure(mock_config):
    """Test generate_digest raises RuntimeError on non-zero CLI exit"""
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stderr = "auth error"

    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(RuntimeError, match="Copilot CLI returned code 1"):
            generate_digest("Title", "Body", [])


def test_generate_digest_retry_on_invalid_json(mock_config):
    """Test generate_digest retries once when response is not valid JSON"""
    valid_json = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    invalid_result = Mock()
    invalid_result.returncode = 0
    invalid_result.stdout = "not valid json at all"

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = valid_json

    with patch('subprocess.run', side_effect=[invalid_result, valid_result]) as mock_run:
        result = generate_digest("Title", "Body", [])

        assert mock_run.call_count == 2
        assert result.translated_title == "Title"


def test_generate_digest_fallback_on_second_failure(mock_config):
    """Test that two consecutive invalid CLI responses yield a safe fallback Digest"""
    bad_result = Mock()
    bad_result.returncode = 0
    bad_result.stdout = "not valid json at all"

    with patch('subprocess.run', return_value=bad_result) as mock_run:
        result = generate_digest("School Trip", "Body text", [])

        assert mock_run.call_count == 2
        assert isinstance(result, Digest)
        assert result.translated_title == "School Trip"
        assert result.topics == []


def test_copilot_command_has_no_tool_flags():
    """ADR 0002 regression: Copilot invocation must never include tool-access flags"""
    cmd = [*_COPILOT_TOOL_FREE_ARGS, "-p", "sample prompt"]
    assert all("--tool" not in arg for arg in cmd), \
        "ADR 0002: tool flags must not appear in _COPILOT_TOOL_FREE_ARGS"
    assert "-p" in cmd, "Non-interactive flag -p must be present"
    assert "--no-color" in cmd


def test_generate_digest_includes_failed_attachment_in_prompt(mock_config):
    """Test that failed attachments are named in the Copilot prompt as unreadable placeholders"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [Attachment(
            filename="form.pdf", url="http://x/form.pdf",
            filetype="pdf", text="", failed=True,
        )])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "form.pdf" in prompt
        assert "could not be extracted" in prompt


def test_generate_digest_prompt_instructs_attachment_source_reference(mock_config):
    """Test the prompt tells the model to cite the attachment filename for info sourced from one"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "see filename.pdf" in prompt


def test_generate_digest_includes_pre_scan_hints_in_prompt(mock_config):
    """Test that detected dates/instructions are surfaced to the model as pre-scan hints"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Hand in the form",
        "topics": [{"heading": "Form", "actions": ["15 aug - lever het formulier in"],
                    "bring": [], "notes": []}],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Gelieve het formulier voor 15 aug in te leveren.", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Pre-scan hints" in prompt
        assert "15 aug" in prompt


def test_generate_digest_omits_pre_scan_hints_when_none_found(mock_config):
    """Test that the prompt has no hints section when no dates/instructions are detected"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Nothing notable.",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Just a friendly note with no dates.", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Pre-scan hints" not in prompt


def test_generate_digest_prompt_demands_topic_grouping(mock_config):
    """The prompt must ask for topic grouping, a separate bring list, and no invented dates"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Summary",
        "topics": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Body", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Group the message into topics" in prompt
        assert "ONE item per entry" in prompt
        assert "NEVER invent a date" in prompt
        assert "Order topics by urgency" in prompt
        assert "which group or class" in prompt
        assert "date not specified" in prompt
        assert "Purchase the" in prompt
        assert "24-hour HH:MM" in prompt
        assert "Never use" in prompt and "AM/PM" in prompt
        assert "at most ONE entry per real-world event" in prompt


def test_dict_to_digest_accepts_undated_entries():
    """An entry with no date prefix is valid content, not a schema violation"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{
            "heading": "School supplies",
            "actions": ["Provide the listed school supplies"],
            "bring": ["12 colouring pencils", "headphones"],
            "notes": [],
        }],
    }
    digest = _dict_to_digest(data)
    assert digest.topics[0].bring == ["12 colouring pencils", "headphones"]


def test_dict_to_digest_drops_topics_with_no_entries():
    """A heading with nothing under it is noise and must not reach the reader"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [
            {"heading": "Empty", "actions": [], "bring": [], "notes": []},
            {"heading": "Real", "actions": ["Do the thing"], "bring": [], "notes": []},
        ],
    }
    digest = _dict_to_digest(data)
    assert [t.heading for t in digest.topics] == ["Real"]


def test_dict_to_digest_defaults_missing_entry_lists():
    """A topic may omit lists it has nothing for"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [{"heading": "Trip", "actions": ["Pack a bag"]}],
    }
    digest = _dict_to_digest(data)
    assert digest.topics[0].bring == []
    assert digest.topics[0].notes == []


def test_dict_to_digest_rejects_non_object_topic():
    data = {"translated_title": "Test", "tldr": "Summary", "topics": ["not an object"]}
    with pytest.raises(ValueError, match="must be an object"):
        _dict_to_digest(data)


def test_generate_digest_retry_prompt_demands_target_language(mock_config):
    """Test the retry prompt explicitly requires the configured reader language"""
    mock_config.TRANSLATION_LANGUAGE = "it"
    invalid_result = Mock()
    invalid_result.returncode = 0
    invalid_result.stdout = "not valid json"

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = json.dumps({
        "translated_title": "Titolo",
        "tldr": "Riassunto",
        "topics": [],
    })

    with patch('subprocess.run', side_effect=[invalid_result, valid_result]) as mock_run:
        generate_digest("Title", "Body", [])

        retry_prompt = mock_run.call_args_list[1][0][0][
            mock_run.call_args_list[1][0][0].index("-p") + 1
        ]
        assert "written in it" in retry_prompt


def test_generate_digest_retries_when_first_response_has_no_content(mock_config):
    """Test that an empty-content digest (valid JSON, but no tldr/items) triggers a retry"""
    empty_result = Mock()
    empty_result.returncode = 0
    empty_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "",
        "topics": [],
    })

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Now with content",
        "topics": [],
    })

    with patch('subprocess.run', side_effect=[empty_result, valid_result]) as mock_run:
        result = generate_digest("Title", "Body", [])

        assert mock_run.call_count == 2
        assert result.tldr == "Now with content"


def test_extract_action_hints_finds_dutch_date():
    hints = _extract_action_hints("Lever het formulier in voor 15 aug alstublieft.")
    assert any("15 aug" in h for h in hints)


def test_extract_action_hints_finds_time():
    hints = _extract_action_hints("De school start om 08:30 uur.")
    assert any(h == "time: 08:30" for h in hints)


def test_extract_action_hints_finds_imperative_phrase():
    hints = _extract_action_hints("Gelieve het formulier voor vrijdag in te leveren.")
    assert any(h.startswith("instruction:") for h in hints)


def test_extract_action_hints_empty_when_no_matches():
    assert _extract_action_hints("Fijne dag allemaal, tot morgen.") == []


def test_dict_to_digest_deduplicates_entries_within_a_topic():
    """Test that duplicate entries are removed preserving insertion order"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{
            "heading": "Trip",
            "actions": ["15 Aug - sign form", "15 Aug - sign form", "25 Aug - attend"],
            "bring": ["towel", "towel"],
            "notes": ["4 Jul - holiday", "4 Jul - holiday"],
        }],
    }
    digest = _dict_to_digest(data)
    topic = digest.topics[0]
    assert topic.actions == ["15 Aug - sign form", "25 Aug - attend"]
    assert topic.bring == ["towel"]
    assert topic.notes == ["4 Jul - holiday"]


def test_dict_to_digest_rejects_empty_digest():
    """Test that a digest with no tldr and no topic content is rejected as content-less"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [],
    }
    with pytest.raises(ValueError, match="no content"):
        _dict_to_digest(data)


def test_dict_to_digest_accepts_tldr_only_digest():
    """Test that a non-empty tldr alone is sufficient content, even with no topics"""
    data = {
        "translated_title": "Test",
        "tldr": "Nothing to do this week.",
        "topics": [],
    }
    digest = _dict_to_digest(data)
    assert digest.tldr == "Nothing to do this week."


def test_dict_to_digest_rejects_non_string_action():
    """Test that a non-string entry in a topic's actions is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{"heading": "T", "actions": [{"text": "15 Aug - sign form"}],
                    "bring": [], "notes": []}],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        _dict_to_digest(data)


def test_dict_to_digest_rejects_blank_note():
    """Test that a blank/whitespace-only entry is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [{"heading": "T", "actions": [], "bring": [], "notes": ["   "]}],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        _dict_to_digest(data)


def test_render_digest_notification_with_items():
    """A topic renders as a heading, its actions, a single bring line, then its notes"""
    data = Digest(
        translated_title="School Event",
        tldr="Summary of event.",
        topics=[Topic(
            heading="School trip",
            actions=["15 Aug - be at school by 08:20"],
            bring=["gym shoes", "towel"],
            notes=["16 Jul - studiedag, no school"],
        )],
    )
    result = render_digest_notification(data)
    assert result == (
        "Summary of event.\n\n"
        "\u2501 School trip\n"
        "\u25b8 15 Aug - be at school by 08:20\n"
        "\U0001F392 Bring: gym shoes, towel\n"
        "\u00b7 16 Jul - studiedag, no school"
    )


def test_render_digest_notification_separates_topics():
    """Distinct subjects stay visually separated instead of merging into one list"""
    data = Digest(
        translated_title="Class Letter",
        tldr="Two subjects.",
        topics=[
            Topic(heading="School supplies", actions=[], bring=["blue pen"], notes=[]),
            Topic(heading="Tests", actions=[], bring=[], notes=["07 Sep - topography"]),
        ],
    )
    result = render_digest_notification(data)
    assert "\u2501 School supplies\n\U0001F392 Bring: blue pen" in result
    assert "\u2501 Tests\n\u00b7 07 Sep - topography" in result
    assert result.count("\u2501") == 2


def test_render_digest_notification_tldr_fallback():
    """Test rendering emits 'No action needed' when no topic carries an action or bring item"""
    data = Digest(
        translated_title="School Info",
        tldr="The school will be closed for renovation.",
        topics=[],
    )
    result = render_digest_notification(data)
    assert result == "The school will be closed for renovation.\n\nNo action needed"


def test_render_digest_notification_notes_only_needs_no_action():
    """An informational post with only notes still tells the parent there is nothing to do"""
    data = Digest(
        translated_title="Newsletter",
        tldr="This week's newsletter.",
        topics=[Topic(heading="", actions=[], bring=[], notes=["16 Jul - studiedag"])],
    )
    result = render_digest_notification(data)
    assert "No action needed" in result
    assert "\u00b7 16 Jul - studiedag" in result


def test_render_digest_notification_with_attachments():
    """Test rendering shows no filename lines for successful attachments"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data)
    assert result == "\u25b8 15 Aug - sign form"


def test_render_digest_notification_with_failed_attachments():
    """Test that failed attachments appear as a generic warning without filename or URL"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(
        data,
        failed_attachments=["broken.pdf"],
    )
    assert "\u26a0" in result
    assert "broken.pdf" not in result
    assert "socialschools" not in result


def test_render_digest_notification_with_original_title_and_date():
    """Test that the post date/time is shown prominently at the top, and the footer has no date"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data, original_title="Formulier reis", post_date="1 Jul 10:00")
    assert result == (
        "\U0001F4C5 1 Jul 10:00\n\n"
        "\u25b8 15 Aug - sign form\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\""
    )


def test_render_digest_notification_with_original_title_no_date():
    """Test that no date line is rendered when no post date is available"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[],
    )
    result = render_digest_notification(data, original_title="Formulier reis")
    assert result == (
        "No action needed\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\""
    )


def test_render_digest_notification_with_date_no_original_title():
    """Test that the date line still renders even when there is no footer"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data, post_date="23 Jun 15:00")
    assert result == "\U0001F4C5 23 Jun 15:00\n\n\u25b8 15 Aug - sign form"


def test_render_digest_notification_without_original_title_omits_footer():
    """Test that no footer is rendered when original_title is not provided"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        topics=[Topic(heading="", actions=["15 Aug - sign form"], bring=[], notes=[])],
    )
    result = render_digest_notification(data)
    assert "To find this post" not in result


def _mock_article_with_date_text(text):
    article = Mock()
    date_el = Mock()
    date_el.inner_text.return_value = text
    article.query_selector.return_value = date_el
    return article


def test_get_post_date_valid_with_time():
    """Test that real Social Schools text ('D month om HH:MM') keeps both date and time"""
    article = _mock_article_with_date_text("7 juli om 13:19")
    assert _get_post_date(article) == "7 Jul 13:19"


def test_get_post_date_valid_without_time():
    """Test that a date with no time suffix still parses to just 'D Mon'"""
    article = _mock_article_with_date_text("1 juli")
    assert _get_post_date(article) == "1 Jul"


@pytest.mark.parametrize("dutch,expected_abbr", [
    ("januari", "Jan"), ("februari", "Feb"), ("maart", "Mar"), ("april", "Apr"),
    ("mei", "May"), ("juni", "Jun"), ("juli", "Jul"), ("augustus", "Aug"),
    ("september", "Sep"), ("oktober", "Oct"), ("november", "Nov"), ("december", "Dec"),
])
def test_get_post_date_all_dutch_months(dutch, expected_abbr):
    """Test that every Dutch month name maps to the correct English abbreviation"""
    article = _mock_article_with_date_text(f"23 {dutch} om 09:05")
    assert _get_post_date(article) == f"23 {expected_abbr} 09:05"


def test_get_post_date_case_insensitive():
    """Test that month names are matched regardless of case"""
    article = _mock_article_with_date_text("3 JULI om 14:09")
    assert _get_post_date(article) == "3 Jul 14:09"


def test_get_post_date_single_digit_day():
    """Test that a single-digit day is not zero-padded"""
    article = _mock_article_with_date_text("3 juli om 14:09")
    assert _get_post_date(article) == "3 Jul 14:09"


def test_get_post_date_no_date_element():
    """Test that a missing date link (no a.meta-info) returns None"""
    article = Mock()
    article.query_selector.return_value = None
    assert _get_post_date(article) is None


def test_get_post_date_empty_text():
    """Test that an empty date text returns None"""
    article = _mock_article_with_date_text("")
    assert _get_post_date(article) is None


def test_get_post_date_unparseable_text():
    """Test that text without a recognizable day/month returns None instead of raising"""
    article = _mock_article_with_date_text("not-a-date")
    assert _get_post_date(article) is None


def test_get_post_date_ignores_edited_suffix():
    """An edited post appends ', bijgewerkt ...'; the original posting time must win"""
    article = _mock_article_with_date_text("7 juli om 13:19,\xa0bijgewerkt\xa07 juli om 16:47")
    assert _get_post_date(article) == "7 Jul 13:19"


@pytest.mark.parametrize("word,expected_day", [
    ("vandaag", 21), ("gisteren", 20), ("eergisteren", 19),
])
def test_get_post_date_resolves_relative_day(word, expected_day):
    """Recent posts are labelled 'vandaag'/'gisteren' and must resolve to a real date"""
    article = _mock_article_with_date_text(f"{word} om 15:47,\xa0bijgewerkt\xa0{word} om 16:47")
    assert _get_post_date(article, today=date(2026, 8, 21)) == f"{expected_day} Aug 15:47"


def test_get_post_date_resolves_past_weekday():
    """'afgelopen dinsdag' resolves to the most recent past Tuesday"""
    article = _mock_article_with_date_text("afgelopen dinsdag om 15:39")
    # 2026-08-21 is a Friday, so the preceding Tuesday is the 18th.
    assert _get_post_date(article, today=date(2026, 8, 21)) == "18 Aug 15:39"


def test_get_post_date_weekday_matching_today_resolves_to_last_week():
    """A weekday label never means today, so it resolves a full week back"""
    article = _mock_article_with_date_text("afgelopen vrijdag om 09:00")
    assert _get_post_date(article, today=date(2026, 8, 21)) == "14 Aug 09:00"


def test_get_post_date_relative_without_time():
    """A relative label with no time still yields a date"""
    article = _mock_article_with_date_text("gisteren")
    assert _get_post_date(article, today=date(2026, 8, 21)) == "20 Aug"


# =============================================================================
# LLM PROVIDER TESTS
# =============================================================================


def test_get_provider_defaults_to_copilot(mock_config):
    """Default config selects the Copilot CLI provider"""
    assert isinstance(get_provider(), CopilotCliProvider)


def test_get_provider_openai_compatible():
    """LLM_PROVIDER=openai_compatible builds the HTTP adapter from config"""
    cfg = Config(
        SCRAPED_WEBSITE_USER="u", SCRAPED_WEBSITE_PASSWORD="p",
        PUSHBULLET_API_KEYS="Me:t", LLM_PROVIDER="openai_compatible",
        LLM_BASE_URL="http://localhost:11434/v1", LLM_MODEL="llama3.1",
    )
    with patch('get_social_schools_news.load_config', return_value=cfg):
        import get_social_schools_news
        get_social_schools_news.config = None
        provider = get_provider()
        get_social_schools_news.config = None
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.model == "llama3.1"


def test_get_provider_unknown_raises():
    """An unrecognized LLM_PROVIDER fails fast with a clear error"""
    cfg = Config(
        SCRAPED_WEBSITE_USER="u", SCRAPED_WEBSITE_PASSWORD="p",
        PUSHBULLET_API_KEYS="Me:t", LLM_PROVIDER="bogus",
    )
    with patch('get_social_schools_news.load_config', return_value=cfg):
        import get_social_schools_news
        get_social_schools_news.config = None
        with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER"):
            get_provider()
        get_social_schools_news.config = None


def test_openai_compatible_requires_base_url_and_model():
    """The HTTP provider refuses to construct without base_url and model"""
    with pytest.raises(RuntimeError, match="LLM_BASE_URL is required"):
        OpenAICompatibleProvider(base_url="", model="x")
    with pytest.raises(RuntimeError, match="LLM_MODEL is required"):
        OpenAICompatibleProvider(base_url="http://x/v1", model="")


def test_openai_compatible_complete_returns_content():
    """A well-formed OpenAI-compatible response yields the message content"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "  hello  "}}]
    }
    with patch('requests.post', return_value=mock_resp) as mock_post:
        result = provider.complete("prompt text")
    assert result == "hello"
    url = mock_post.call_args[0][0]
    assert url == "http://x/v1/chat/completions"


def test_openai_compatible_requests_deterministic_sampling():
    """Digest extraction must not sample at the provider's creative default temperature"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
    with patch('requests.post', return_value=mock_resp) as mock_post:
        provider.complete("prompt text")
    payload = json.loads(mock_post.call_args[1]["data"])
    assert payload["temperature"] == 0


def test_openai_compatible_never_sends_tools():
    """ADR 0002 regression: the HTTP payload must never include tools/functions"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch('requests.post', return_value=mock_resp) as mock_post:
        provider.complete("prompt text")
    payload = json.loads(mock_post.call_args[1]["data"])
    assert "tools" not in payload
    assert "functions" not in payload
    assert payload["stream"] is False


def test_openai_compatible_sends_bearer_token_when_key_set():
    """An API key is sent as a Bearer token; absent key sends no Authorization header"""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with_key = OpenAICompatibleProvider(base_url="http://x/v1", model="m", api_key="secret")
    with patch('requests.post', return_value=mock_resp) as mock_post:
        with_key.complete("p")
    assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer secret"

    no_key = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with patch('requests.post', return_value=mock_resp) as mock_post:
        no_key.complete("p")
    assert "Authorization" not in mock_post.call_args[1]["headers"]


def test_openai_compatible_raises_on_error_status():
    """A non-200 status from the endpoint raises RuntimeError"""
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    mock_resp = Mock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"
    with patch('requests.post', return_value=mock_resp):
        with pytest.raises(RuntimeError, match="returned status 401"):
            provider.complete("p")


def test_generate_digest_via_openai_compatible_provider():
    """generate_digest routes through the HTTP provider when configured, not the CLI"""
    cfg = Config(
        SCRAPED_WEBSITE_USER="u", SCRAPED_WEBSITE_PASSWORD="p",
        PUSHBULLET_API_KEYS="Me:t", LLM_PROVIDER="openai_compatible",
        LLM_BASE_URL="http://localhost:11434/v1", LLM_MODEL="llama3.1",
    )
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": json.dumps({
        "translated_title": "School Trip",
        "tldr": "Bring shoes",
        "topics": [{"heading": "Trip", "actions": ["15 Aug - bring shoes"],
                    "bring": [], "notes": []}],
    })}}]}
    with patch('get_social_schools_news.load_config', return_value=cfg):
        import get_social_schools_news
        get_social_schools_news.config = None
        with patch('requests.post', return_value=mock_resp) as mock_post, \
                patch('subprocess.run') as mock_run:
            result = generate_digest("School Trip", "Body", [])
        get_social_schools_news.config = None
    mock_post.assert_called_once()
    mock_run.assert_not_called()
    assert isinstance(result, Digest)
    assert result.translated_title == "School Trip"


def test_translation_mode_uses_no_llm_provider(mock_playwright):
    """DIGEST_ENABLED=false must never build a provider or hit subprocess/HTTP"""
    cfg = Config(
        SCRAPED_WEBSITE_USER="u", SCRAPED_WEBSITE_PASSWORD="p",
        PUSHBULLET_API_KEYS="Me:t", DIGEST_ENABLED=False,
    )
    playwright, browser, context, page = mock_playwright

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

    with patch('get_social_schools_news.load_config', return_value=cfg):
        import get_social_schools_news
        get_social_schools_news.config = None
        with patch('get_social_schools_news.get_provider') as mock_get_provider, \
                patch('get_social_schools_news.translate', side_effect=lambda t, dest=None: f"EN:{t}"), \
                patch('get_social_schools_news.send_multilingual_notification') as mock_notify, \
                patch('requests.post') as mock_post, \
                patch('subprocess.run') as mock_run:
            process_article_content(playwright, browser, context, article)
        get_social_schools_news.config = None

    mock_get_provider.assert_not_called()
    mock_post.assert_not_called()
    mock_run.assert_not_called()
    mock_notify.assert_called_once()


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
    """Test processing PDF links returns Attachment objects with no failures"""
    playwright, browser, context = Mock(), Mock(), Mock()

    # Mock PDF links
    mock_link1 = Mock()
    mock_link1.get_attribute.return_value = "http://example.com/test1.pdf"
    mock_link2 = Mock()
    mock_link2.get_attribute.return_value = "http://example.com/test2.pdf"
    pdf_links = [mock_link1, mock_link2]

    with patch('get_social_schools_news._download_pdf') as mock_download, \
         patch('get_social_schools_news.extract_text') as mock_extract, \
         patch('tempfile.TemporaryDirectory'):

        mock_extract.return_value = "PDF content"

        attachments = process_pdf_links(playwright, browser, context, pdf_links)

        assert mock_download.call_count == 2
        assert mock_extract.call_count == 2
        assert all(isinstance(a, Attachment) for a in attachments)
        assert [a.filename for a in attachments] == ["test1.pdf", "test2.pdf"]
        assert all(a.text == "PDF content" for a in attachments)
        assert all(not a.failed for a in attachments)


def test_process_pdf_links_partial_failure():
    """Test that a failing PDF is recorded with failed=True without stopping other attachments"""
    playwright, browser, context = Mock(), Mock(), Mock()

    mock_link1 = Mock()
    mock_link1.get_attribute.return_value = "http://example.com/ok.pdf"
    mock_link2 = Mock()
    mock_link2.get_attribute.return_value = "http://example.com/broken.pdf"
    pdf_links = [mock_link1, mock_link2]

    def download_side_effect(url, path, browser_context=None):
        if "broken" in url:
            raise Exception("404 Not Found")

    with patch('get_social_schools_news._download_pdf', side_effect=download_side_effect), \
         patch('get_social_schools_news.extract_text', return_value="OK content"), \
         patch('tempfile.TemporaryDirectory'):
        attachments = process_pdf_links(playwright, browser, context, pdf_links)

    assert len(attachments) == 2
    ok, broken = attachments
    assert ok.filename == "ok.pdf" and not ok.failed and ok.text == "OK content"
    assert broken.filename == "broken.pdf" and broken.failed


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
    """Test processing DOCX links returns Attachment objects"""
    playwright, browser, context = Mock(), Mock(), Mock()

    # Mock DOCX link
    mock_link = Mock()
    mock_link.get_attribute.return_value = "http://example.com/test.docx"
    docx_links = [mock_link]

    with patch('get_social_schools_news._download_docx') as mock_download, \
         patch('get_social_schools_news.extract_text_from_docx') as \
         mock_extract, \
         patch('tempfile.TemporaryDirectory'):

        mock_extract.return_value = "DOCX content"

        attachments = process_docx_links(playwright, browser, context, docx_links)

        mock_download.assert_called_once()
        mock_extract.assert_called_once()
        assert len(attachments) == 1
        assert isinstance(attachments[0], Attachment)
        assert attachments[0].filename == "test.docx"
        assert attachments[0].text == "DOCX content"
        assert not attachments[0].failed


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
            PUSHBULLET_API_KEYS="Test:testkey"
        )
        mock_get_config.return_value = mock_config

        login_to_website(page)

        page.goto.assert_called_once_with(
            "https://app.socialschools.eu/home", wait_until="domcontentloaded"
        )
        username_field.wait_for.assert_called_once_with(state="visible", timeout=60000)
        username_field.fill.assert_called_once_with("test@example.com")
        password_field.wait_for.assert_called_once_with(state="visible", timeout=60000)
        password_field.fill.assert_called_once_with("testpass")
        password_field.press.assert_called_once_with("Enter")
        page.wait_for_url.assert_called_once_with(
            "https://app.socialschools.eu/home**",
            wait_until="domcontentloaded",
            timeout=60000,
        )


def test_login_to_website_username_field_not_found(mock_playwright):
    """Test login failure when username field is not found"""
    playwright, browser, context, page = mock_playwright

    username_field = Mock()
    username_field.wait_for.side_effect = PlaywrightTimeoutError("not found")
    page.locator.return_value = username_field

    with pytest.raises(Exception, match="Username field not found"):
        login_to_website(page)


def test_login_to_website_password_field_not_found(mock_playwright):
    """Test login failure when password field is not found"""
    playwright, browser, context, page = mock_playwright

    username_field = Mock()
    password_field = Mock()
    password_field.wait_for.side_effect = PlaywrightTimeoutError("not found")

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
    article.wait_for_selector.assert_any_call("span[as='div']", timeout=10000)


def test_expand_full_text_no_button():
    """Test expanding full text when no 'Meer weergeven' button exists"""
    article = Mock()
    article.query_selector.return_value = None

    expand_full_text(article)

    article.query_selector.assert_called_once()
    article.wait_for_selector.assert_any_call("span[as='div']", timeout=10000)


def test_expand_full_text_timeout_is_non_fatal():
    """A missing or delayed full-text block must not abort the whole run."""
    article = Mock()
    article.query_selector.return_value = None
    article.wait_for_selector.side_effect = [TimeoutError("missing full-text block"), None]

    expand_full_text(article)

    article.query_selector.assert_called_once_with("button:has-text('Meer weergeven')")
    assert article.wait_for_selector.call_args_list[0].args == ("span[as='div']",)
    assert article.wait_for_selector.call_args_list[0].kwargs == {"timeout": 10000}
    assert article.wait_for_selector.call_count == 2


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

    with patch('get_social_schools_news.load_processed_articles',
               return_value=[]) as mock_load, \
         patch('get_social_schools_news.save_processed_article') as mock_save, \
         patch('get_social_schools_news.expand_full_text') as mock_expand, \
         patch('get_social_schools_news.process_article_content') as mock_process:

        process_all_articles(playwright, browser, context, page)

        page.locator.assert_called_once_with("div[role='feed']")
        page.locator.return_value.wait_for.assert_called_once_with(
            state="visible", timeout=60000
        )

        mock_load.assert_called()
        mock_expand.assert_called_once_with(article)
        mock_process.assert_called_once_with(
            playwright, browser, context, article
        )
        mock_save.assert_called_once_with("test_article_id")


def test_process_all_articles_feed_not_found(mock_playwright):
    """Test process_all_articles raises when feed element is not found"""
    playwright, browser, context, page = mock_playwright
    page.query_selector.return_value = None

    with pytest.raises(Exception, match="Feed element not found"):
        process_all_articles(playwright, browser, context, page)


def test_process_all_articles_no_articles(mock_playwright):
    """Test process_all_articles returns quietly when feed is empty"""
    playwright, browser, context, page = mock_playwright

    feed = Mock()
    feed.query_selector_all.return_value = []
    page.query_selector.return_value = feed

    with patch('get_social_schools_news.process_article_content') as mock_process:
        process_all_articles(playwright, browser, context, page)
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

    with patch('get_social_schools_news.load_processed_articles',
               return_value=["processed_article_id"]), \
         patch('get_social_schools_news.process_article_content') as mock_process:

        process_all_articles(playwright, browser, context, page)

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

    with patch('get_social_schools_news.load_processed_articles', return_value=[]), \
         patch('get_social_schools_news.save_processed_article') as mock_save, \
         patch('get_social_schools_news.expand_full_text'), \
         patch('get_social_schools_news.process_article_content',
               side_effect=[RuntimeError("Digest failed"), True]) as mock_process:

        process_all_articles(playwright, browser, context, page)

        assert mock_process.call_count == 2
        mock_save.assert_called_once_with("article_2")  # article_1 failed, not saved


def test_run_function_success(mock_playwright):
    """Test successful run function execution"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/home/dashboard"
    expected_browser = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or "/tmp/test-chrome"

    with patch('get_social_schools_news.resolve_browser_executable_path', return_value=expected_browser), \
         patch('get_social_schools_news.login_to_website') as mock_login, \
         patch('get_social_schools_news.process_all_articles') as \
         mock_process, \
         patch('get_social_schools_news._check_copilot_available'):

        run(playwright)

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            executable_path=expected_browser
        )
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

        send_notification("Test", "Body", "Custom:custom_api_key")

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

    with patch('get_social_schools_news.send_multilingual_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest') as mock_digest, \
         patch('get_social_schools_news.process_pdf_links') as mock_pdf, \
         patch('get_social_schools_news.process_docx_links') as mock_docx:

        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="",
            topics=[Topic(heading="", actions=["15 Aug - action"], bring=[], notes=[])],
        )
        mock_pdf.return_value = [Attachment(
            filename="doc.pdf", url="http://example.com/doc.pdf",
            filetype="pdf", text="PDF text",
        )]
        mock_docx.return_value = [Attachment(
            filename="doc.docx", url="http://example.com/doc.docx",
            filetype="docx", text="DOCX text",
        )]

        process_article_content(playwright, browser, context, article)

        # Should process both PDF and DOCX
        mock_pdf.assert_called_once_with(playwright, browser, context,
                                         [pdf_link])
        mock_docx.assert_called_once_with(playwright, browser, context,
                                          [docx_link])
        mock_digest.assert_called_once_with(
            "Test Title", "Test Body",
            [
                Attachment(filename="doc.pdf", url="http://example.com/doc.pdf", filetype="pdf", text="PDF text"),
                Attachment(filename="doc.docx", url="http://example.com/doc.docx", filetype="docx", text="DOCX text"),
            ],
            language="en",
        )
        mock_notify.assert_called_once_with({
            "en": (
                "Translated Title",
                "\u25b8 15 Aug - action\n\n"
                "To find this post in Social Schools, look for: \"Test Title\"",
            ),
        })


# =============================================================================
# ERROR HANDLING AND ROBUSTNESS TESTS
# =============================================================================


def test_process_article_content_digest_failure(mock_playwright, mock_config):
    """Test that digest failure sends an operational notice and re-raises (leaving article unmarked)"""
    playwright, browser, context, page = mock_playwright

    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest',
               side_effect=RuntimeError("Copilot CLI returned code 1")):
        with pytest.raises(RuntimeError):
            process_article_content(playwright, browser, context, article)

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

    with patch('get_social_schools_news.send_multilingual_notification') as mock_notify, \
         patch('get_social_schools_news.translate', return_value="Translated") as mock_translate, \
         patch('get_social_schools_news.generate_digest') as mock_digest:

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_not_called()
        assert mock_translate.call_count == 2  # title + body
        mock_notify.assert_called_once_with({"en": ("Translated", "Translated")})


def test_check_copilot_available_success():
    """Test startup check passes when copilot responds with exit 0"""
    mock_result = Mock()
    mock_result.returncode = 0
    with patch('subprocess.run', return_value=mock_result):
        _check_copilot_available()  # should not raise


def test_check_copilot_available_not_found():
    """Test startup check raises RuntimeError when copilot is not in PATH"""
    with patch('subprocess.run', side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Copilot CLI not found"):
            _check_copilot_available()


def test_check_copilot_available_failure():
    """Test startup check raises RuntimeError on non-zero exit"""
    mock_result = Mock()
    mock_result.returncode = 1
    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(RuntimeError, match="health check failed"):
            _check_copilot_available()


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

    with patch('get_social_schools_news.save_processed_article',
               return_value=True) as mock_save, \
         patch('get_social_schools_news.expand_full_text'), \
         patch('get_social_schools_news.process_article_content'):

        process_all_articles(playwright, browser, context, page)

        expected_id = "Fallback Title_2023-12-01T10:00:00Z"
        mock_save.assert_called_once_with(expected_id)


def test_config_missing_translation_language():
    """Test config loading with missing TRANSLATION_LANGUAGE"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
            'PUSHBULLET_API_KEYS': 'Test:api_key_123'
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: default)

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.TRANSLATION_LANGUAGE == 'en'


# --- Admin alerting ----------------------------------------------------------


def _admin_config(**overrides):
    import get_social_schools_news
    cfg = Config(
        SCRAPED_WEBSITE_USER="u",
        SCRAPED_WEBSITE_PASSWORD="p",
        PUSHBULLET_API_KEYS="Test:test_api_key",
        EMAIL_SENDER="sender@example.com",
        EMAIL_APP_PASSWORD="app_password",
        **overrides,
    )
    get_social_schools_news.config = cfg
    return cfg


def test_notify_admin_noop_when_unconfigured():
    _admin_config()
    with patch('get_social_schools_news._send_pushbullet') as mock_push, \
         patch('get_social_schools_news._send_email') as mock_email:
        notify_admin("Something broke")
    mock_push.assert_not_called()
    mock_email.assert_not_called()


def test_notify_admin_sends_to_both_channels():
    _admin_config(ADMIN_PUSHBULLET_API_KEY="o.admin", ADMIN_EMAIL="admin@example.com")
    with patch('get_social_schools_news._send_pushbullet') as mock_push, \
         patch('get_social_schools_news._send_email') as mock_email:
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


def test_notify_admin_never_raises_when_channel_fails():
    _admin_config(ADMIN_PUSHBULLET_API_KEY="o.admin", ADMIN_EMAIL="admin@example.com")
    with patch('get_social_schools_news._send_pushbullet', side_effect=RuntimeError("push down")), \
         patch('get_social_schools_news._send_email', side_effect=RuntimeError("smtp down")) as mock_email:
        notify_admin("Digest degraded")
    # Email is still attempted even though Pushbullet blew up first.
    mock_email.assert_called_once()


def test_process_article_content_returns_false_when_body_unreadable():
    article = Mock()
    article.query_selector.return_value = None
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.notify_admin') as mock_admin, \
         patch('get_social_schools_news.send_notification') as mock_send:
        result = process_article_content(Mock(), Mock(), Mock(), article)

    assert result is False
    mock_send.assert_not_called()
    mock_admin.assert_called_once()


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

    with patch('get_social_schools_news.load_processed_articles', return_value=[]), \
         patch('get_social_schools_news.save_processed_article') as mock_save, \
         patch('get_social_schools_news.expand_full_text'), \
         patch('get_social_schools_news.process_article_content', return_value=False):

        process_all_articles(playwright, browser, context, page)

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

    with patch('get_social_schools_news.load_processed_articles', return_value=[]), \
         patch('get_social_schools_news.save_processed_article') as mock_save, \
         patch('get_social_schools_news.expand_full_text'), \
         patch('get_social_schools_news.notify_admin') as mock_admin, \
         patch('get_social_schools_news.process_article_content',
               side_effect=RuntimeError("Digest failed")):

        process_all_articles(playwright, browser, context, page)

    mock_save.assert_not_called()
    mock_admin.assert_called_once()


def test_load_config_reads_admin_settings(tmp_path, monkeypatch):
    config_file = tmp_path / "config.ini"
    config_file.write_text(
        "[DEFAULT]\n"
        "SCRAPED_WEBSITE_USER = u\n"
        "SCRAPED_WEBSITE_PASSWORD = p\n"
        "ADMIN_PUSHBULLET_API_KEY = o.admin\n"
        "ADMIN_EMAIL = admin@example.com\n"
    )
    monkeypatch.chdir(tmp_path)
    result = load_config()

    assert result.ADMIN_PUSHBULLET_API_KEY == "o.admin"
    assert result.ADMIN_EMAIL == "admin@example.com"


# =============================================================================
# DIGEST EVALUATION SCORING
#
# Each check below encodes a failure actually observed in a delivered
# notification, so these tests double as regression cases for the scorer.
# =============================================================================


def _digest(topics, tldr="Summary"):
    return Digest(translated_title="T", tldr=tldr, topics=topics)


def test_find_placeholder_dates_flags_invented_date():
    """'XX Sep - Parent evening (date not specified)' was really emitted once"""
    digest = _digest([Topic(heading="Evening",
                            actions=["XX Sep - Parent evening (date not specified)"],
                            bring=[], notes=[])])
    assert evaluate_digests.find_placeholder_dates(digest)


def test_find_placeholder_dates_accepts_undated_entry():
    """An entry with no date at all is correct behaviour, not a placeholder"""
    digest = _digest([Topic(heading="Supplies",
                            actions=["Provide the listed school supplies"],
                            bring=[], notes=[])])
    assert evaluate_digests.find_placeholder_dates(digest) == []


def test_find_near_duplicates_flags_exploded_packing_list():
    """Nine 'Provide your child with X' actions were really emitted once"""
    digest = _digest([Topic(
        heading="Trip",
        actions=[
            "Provide your child with a towel for the school trip",
            "Provide your child with shower gel for the school trip",
            "Provide your child with dry clothes for the school trip",
        ],
        bring=[], notes=[])])
    assert evaluate_digests.find_near_duplicates(digest)


def test_find_near_duplicates_allows_genuinely_distinct_entries():
    """Similarly-shaped but distinct test dates must not be flagged"""
    digest = _digest([Topic(
        heading="Tests",
        actions=[],
        bring=[],
        notes=[
            "07 Sep - topography test tile 1",
            "11 Sep - English song 1",
            "02 Oct - English song 2",
        ])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_near_duplicates_allows_one_entry_per_group():
    """'Group 6B' and 'Group 6C' address different children, not the same one twice"""
    digest = _digest([Topic(
        heading="Class parents",
        actions=[
            "Email the class parent details for group 6B",
            "Email the class parent details for group 6C",
        ],
        bring=[], notes=[])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_near_duplicates_allows_shared_prefix_when_each_names_a_group():
    """A start-time per group repeats wording by necessity"""
    digest = _digest([Topic(
        heading="First school day",
        actions=[],
        bring=[],
        notes=[
            "18 Aug - group 3 starts at 08:30",
            "18 Aug - group 4 starts at 08:35",
            "18 Aug - group 5 starts at 08:40",
        ])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_missing_hint_dates_ignores_newsletter_filler():
    """A museum listing in an attached newsletter obliges no parent"""
    body = ("Tot en met 11 oktober hangt het meisje naast haar ouders in het "
            "museum aan het Klein Heiligland.")
    digest = _digest([Topic(heading="News", actions=[], bring=[], notes=["a note"])])
    assert evaluate_digests.find_missing_hint_dates(digest, body) == []


def test_find_same_date_clusters_flags_one_event_split_across_many_lines():
    """A single field trip restated across arrival/departure/return lines"""
    digest = _digest([Topic(
        heading="Field Trip",
        actions=[
            "01 Sep - Ensure child arrives at school by 08:20 for the 08:30 bus.",
            "01 Sep - Inform after-school care about a possible late return.",
        ],
        bring=[],
        notes=[
            "01 Sep - Field trip to Poldersport is scheduled.",
            "01 Sep - Departure by bus from school at 08:30.",
            "01 Sep - Expected return to school around 14:30.",
        ])])
    warnings = evaluate_digests.find_same_date_clusters(digest)
    assert any("all dated '01 Sep'" in w for w in warnings)


def test_find_same_date_clusters_allows_few_entries_on_one_date():
    digest = _digest([Topic(
        heading="Trip",
        actions=["01 Sep - Sign the permission form."],
        bring=[],
        notes=["01 Sep - Bus departs at 08:30."])])
    assert evaluate_digests.find_same_date_clusters(digest) == []


def test_find_missing_hint_dates_still_flags_school_event():
    """A school trip date is the whole reason the tool exists"""
    body = "Het schoolreisje is op 1 september, we vertrekken om 08:30."
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body) == [
        "source date not in digest: 1 Sep"]


def test_find_structure_problems_allows_many_topics_in_a_newsletter():
    """A full school newsletter really does have a dozen sections"""
    digest = _digest([
        Topic(heading=f"Section {i}", actions=[], bring=[], notes=["a note"])
        for i in range(9)
    ])
    assert evaluate_digests.find_structure_problems(digest, "x" * 6000) == []


def test_find_structure_problems_still_caps_topics_on_a_normal_post():
    digest = _digest([
        Topic(heading=f"Section {i}", actions=[], bring=[], notes=["a note"])
        for i in range(9)
    ])
    problems = evaluate_digests.advisory_warnings(
        digest, {"body": "x" * 1000, "attachments": []})
    assert any("more than the message plausibly has" in p for p in problems)


def test_find_missing_hint_dates_flags_dropped_date():
    body = "Op dinsdag 1 september gaan wij op schoolreisje."
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body) == ["source date not in digest: 1 Sep"]


def test_find_missing_hint_dates_passes_when_date_present():
    body = "Op dinsdag 1 september gaan wij op schoolreisje."
    digest = _digest([Topic(heading="Trip", actions=["01 Sep - school trip"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body) == []


def test_find_bring_repeated_in_actions():
    digest = _digest([Topic(heading="Trip",
                            actions=["Provide a towel for the trip"],
                            bring=["towel"], notes=[])])
    assert evaluate_digests.find_bring_repeated_in_actions(digest)


def test_find_structure_problems_flags_empty_tldr():
    digest = _digest([Topic(heading="T", actions=["Do it"], bring=[], notes=[])], tldr="")
    assert "tldr is empty" in evaluate_digests.find_structure_problems(digest, "body")


def test_find_structure_problems_flags_invented_headings_on_short_post():
    """A 261-char newsletter does not have three subjects"""
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    problems = evaluate_digests.find_structure_problems(digest, "short body")
    assert any("headings likely invented" in p for p in problems)


def test_find_structure_problems_allows_multiple_topics_on_long_post():
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    assert evaluate_digests.find_structure_problems(digest, "x" * 2000) == []


def test_score_recall_counts_hits_and_missing():
    digest = _digest([Topic(heading="Trip",
                            actions=["Child must have a swimming diploma"],
                            bring=[], notes=[])])
    hits, total, missing = evaluate_digests.score_recall(digest, ["swimming diploma", "08:20"])
    assert (hits, total, missing) == (1, 2, ["08:20"])


def test_score_recall_with_no_expectations_is_neutral():
    digest = _digest([Topic(heading="T", actions=["Do it"], bring=[], notes=[])])
    assert evaluate_digests.score_recall(digest, []) == (0, 0, [])


def test_source_text_includes_attachment_content():
    """An obligation stated only in a PDF is still one the digest must carry"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "Lever het formulier in voor 15 aug."}],
    }
    assert "15 aug" in evaluate_digests.source_text(case)


def test_source_text_skips_failed_attachments():
    """A failed extraction has no text, so it cannot be held against the digest"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": True, "text": ""}],
    }
    assert evaluate_digests.source_text(case) == "Zie de bijlage."


def test_structural_violations_flag_date_found_only_in_attachment():
    case = {
        "body": "Zie de bijlage." + "x" * 500,
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "Het schoolreisje is op 1 september."}],
    }
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.structural_violations(digest, case) == []
    assert "source date not in digest: 1 Sep" in evaluate_digests.advisory_warnings(digest, case)


def test_structural_violations_allow_topics_when_attachment_is_long():
    """A short post with a long PDF is not a short message"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "y" * 2000}],
    }
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    assert evaluate_digests.structural_violations(digest, case) == []

