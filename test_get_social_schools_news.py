import json
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
    generate_digest,
    render_digest_notification,
    process_article_content,
    Config,
    Digest,
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
    _extract_action_hints,
)


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


def test_process_article_content(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright

    # Mock article with content
    article = Mock()
    mock_query_selector = article.query_selector.return_value
    mock_query_selector.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            action_items=[],
            key_dates=[],
        )

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_called_once()
        mock_notify.assert_called_once_with(
            title="Translated Title",
            body="Short summary\n\nNo action needed\n\n"
                 "To find this post in Social Schools, look for: \"Test Content\"",
        )


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
         patch('get_social_schools_news.generate_digest') as mock_digest:
        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="Short summary",
            action_items=[],
            key_dates=[],
        )

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_called_once_with("Test Content", "Test Content", [])
        mock_notify.assert_called_once_with(
            title="Translated Title",
            body="Short summary\n\nNo action needed\n\n"
                 "To find this post in Social Schools, look for: \"Test Content\"",
        )


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
            'PUSHBULLET_API_KEYS': 'Test:api_key_123'
        }[key])
        mock_default_section.get = Mock(return_value='it')

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
        "action_items": ["15 Aug - bring gym shoes"],
        "key_dates": ["16 Aug - school closed"],
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
        assert result.action_items == ["15 Aug - bring gym shoes"]


def test_generate_digest_with_attachments(mock_config):
    """Test Digest generation includes attachment text in prompt"""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "translated_title": "Form Required",
        "tldr": "",
        "action_items": ["15 Aug - sign and return the form"],
        "key_dates": [],
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
        "action_items": [],
        "key_dates": [],
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
        assert result.action_items == []
        assert result.key_dates == []


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
        "tldr": "",
        "action_items": [],
        "key_dates": [],
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
        "action_items": [],
        "key_dates": [],
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
        "tldr": "",
        "action_items": ["15 aug - lever het formulier in"],
        "key_dates": [],
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
        "action_items": [],
        "key_dates": [],
    })

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        generate_digest("Title", "Just a friendly note with no dates.", [])

        prompt = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-p") + 1]
        assert "Pre-scan hints" not in prompt


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
        "action_items": [],
        "key_dates": [],
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
        "action_items": [],
        "key_dates": [],
    })

    valid_result = Mock()
    valid_result.returncode = 0
    valid_result.stdout = json.dumps({
        "translated_title": "Title",
        "tldr": "Now with content",
        "action_items": [],
        "key_dates": [],
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


def test_dict_to_digest_deduplicates_action_items_and_key_dates():
    """Test that duplicate action items and key dates are removed preserving insertion order"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "action_items": ["15 Aug - sign form", "15 Aug - sign form", "25 Aug - attend"],
        "key_dates": ["4 Jul - holiday", "4 Jul - holiday"],
    }
    digest = _dict_to_digest(data)
    assert digest.action_items == ["15 Aug - sign form", "25 Aug - attend"]
    assert digest.key_dates == ["4 Jul - holiday"]


def test_dict_to_digest_rejects_empty_digest():
    """Test that a digest with no tldr, action items, or key dates is rejected as content-less"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "action_items": [],
        "key_dates": [],
    }
    with pytest.raises(ValueError, match="no content"):
        _dict_to_digest(data)


def test_dict_to_digest_accepts_tldr_only_digest():
    """Test that a non-empty tldr alone is sufficient content, even with no items"""
    data = {
        "translated_title": "Test",
        "tldr": "Nothing to do this week.",
        "action_items": [],
        "key_dates": [],
    }
    digest = _dict_to_digest(data)
    assert digest.tldr == "Nothing to do this week."


def test_dict_to_digest_rejects_non_string_action_item():
    """Test that a non-string entry in action_items is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "action_items": [{"text": "15 Aug - sign form"}],
        "key_dates": [],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        _dict_to_digest(data)


def test_dict_to_digest_rejects_blank_key_date():
    """Test that a blank/whitespace-only entry in key_dates is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "action_items": [],
        "key_dates": ["   "],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        _dict_to_digest(data)


def test_render_digest_notification_with_items():
    """Test rendering prefixes action items and key dates with bullets under labelled headers"""
    data = Digest(
        translated_title="School Event",
        tldr="Summary of event.",
        action_items=["15 Aug - bring gym shoes"],
        key_dates=["16 Jul - studiedag, no school"],
    )
    result = render_digest_notification(data)
    assert result == (
        "Summary of event.\n\nAction Items:\n\u25b8 15 Aug - bring gym shoes\n\n"
        "Key Dates:\n\u25b8 16 Jul - studiedag, no school"
    )


def test_render_digest_notification_tldr_fallback():
    """Test rendering emits 'No action needed' when no items exist, with tldr shown"""
    data = Digest(
        translated_title="School Info",
        tldr="The school will be closed for renovation.",
        action_items=[],
        key_dates=[],
    )
    result = render_digest_notification(data)
    assert result == "The school will be closed for renovation.\n\nNo action needed"


def test_render_digest_notification_with_attachments():
    """Test rendering shows no filename lines for successful attachments"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        action_items=["15 Aug - sign form"],
        key_dates=[],
    )
    result = render_digest_notification(data)
    assert result == "Action Items:\n\u25b8 15 Aug - sign form"


def test_render_digest_notification_with_failed_attachments():
    """Test that failed attachments appear as a generic warning without filename or URL"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        action_items=["15 Aug - sign form"],
        key_dates=[],
    )
    result = render_digest_notification(
        data,
        failed_attachments=["broken.pdf"],
    )
    assert "\u26a0" in result
    assert "broken.pdf" not in result
    assert "socialschools" not in result


def test_render_digest_notification_with_original_title_and_date():
    """Test that the footer includes the original post title and date for traceability"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        action_items=["15 Aug - sign form"],
        key_dates=[],
    )
    result = render_digest_notification(data, original_title="Formulier reis", post_date="1 Jul")
    assert result == (
        "Action Items:\n\u25b8 15 Aug - sign form\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\" (1 Jul)"
    )


def test_render_digest_notification_with_original_title_no_date():
    """Test that the footer omits the date parenthetical when no post date is available"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        action_items=[],
        key_dates=[],
    )
    result = render_digest_notification(data, original_title="Formulier reis")
    assert result == (
        "No action needed\n\n"
        "To find this post in Social Schools, look for: \"Formulier reis\""
    )


def test_render_digest_notification_without_original_title_omits_footer():
    """Test that no footer is rendered when original_title is not provided"""
    data = Digest(
        translated_title="Trip Form",
        tldr="",
        action_items=["15 Aug - sign form"],
        key_dates=[],
    )
    result = render_digest_notification(data)
    assert "To find this post" not in result


def test_get_post_date_valid():
    """Test that a valid datetime attribute is formatted as 'D Mon'"""
    article = Mock()
    time_el = Mock()
    time_el.get_attribute.return_value = "2026-07-01T10:00:00+02:00"
    article.query_selector.return_value = time_el
    assert _get_post_date(article) == "1 Jul"


def test_get_post_date_no_time_element():
    """Test that missing <time> element returns None"""
    article = Mock()
    article.query_selector.return_value = None
    assert _get_post_date(article) is None


def test_get_post_date_no_datetime_attribute():
    """Test that a <time> element without a datetime attribute returns None"""
    article = Mock()
    time_el = Mock()
    time_el.get_attribute.return_value = None
    article.query_selector.return_value = time_el
    assert _get_post_date(article) is None


def test_get_post_date_invalid_format():
    """Test that an unparseable datetime attribute returns None instead of raising"""
    article = Mock()
    time_el = Mock()
    time_el.get_attribute.return_value = "not-a-date"
    article.query_selector.return_value = time_el
    assert _get_post_date(article) is None


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
               side_effect=[RuntimeError("Digest failed"), None]) as mock_process:

        process_all_articles(playwright, browser, context, page)

        assert mock_process.call_count == 2
        mock_save.assert_called_once_with("article_2")  # article_1 failed, not saved


def test_run_function_success(mock_playwright):
    """Test successful run function execution"""
    playwright, browser, context, page = mock_playwright
    page.url = "https://app.socialschools.eu/home/dashboard"

    with patch('get_social_schools_news.login_to_website') as mock_login, \
         patch('get_social_schools_news.process_all_articles') as \
         mock_process, \
         patch('get_social_schools_news._check_copilot_available'):

        run(playwright)

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            executable_path='/usr/bin/chromium-browser'
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
        "time": None,
    }[selector]

    # Mock PDF and DOCX links
    pdf_link = Mock()
    docx_link = Mock()
    article.query_selector_all.side_effect = lambda selector: {
        "a[href*='.pdf']": [pdf_link],
        "a[href*='.docx']": [docx_link],
    }.get(selector, [])

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.generate_digest') as mock_digest, \
         patch('get_social_schools_news.process_pdf_links') as mock_pdf, \
         patch('get_social_schools_news.process_docx_links') as mock_docx:

        mock_digest.return_value = Digest(
            translated_title="Translated Title",
            tldr="",
            action_items=["15 Aug - action"],
            key_dates=[],
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
            ]
        )
        mock_notify.assert_called_once_with(
            title="Translated Title",
            body="Action Items:\n\u25b8 15 Aug - action\n\n"
                 "To find this post in Social Schools, look for: \"Test Title\"",
        )


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

    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate', return_value="Translated") as mock_translate, \
         patch('get_social_schools_news.generate_digest') as mock_digest:

        process_article_content(playwright, browser, context, article)

        mock_digest.assert_not_called()
        assert mock_translate.call_count == 2  # title + body
        mock_notify.assert_called_once_with(title="Translated", body="Translated")


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
        mock_default_section.get = Mock(return_value='en')

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.TRANSLATION_LANGUAGE == 'en'
