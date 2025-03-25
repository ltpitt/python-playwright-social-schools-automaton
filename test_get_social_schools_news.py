import pytest
import os
import sys
from unittest.mock import Mock, patch
import configparser

# Add the current directory to Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from get_social_schools_news import (
    load_processed_articles,
    save_processed_article,
    translate,
    send_notification,
    process_article_content,
    Config,
    get_config
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
    with patch('get_social_schools_news.load_config', return_value=test_config):
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
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE', str(tmp_path / 'processed.json')):
        # Test empty file
        assert load_processed_articles() == []
        
        # Test with existing articles
        with open(tmp_path / 'processed.json', 'w') as f:
            f.write('["article1", "article2"]')
        assert load_processed_articles() == ["article1", "article2"]

def test_save_processed_article(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE', str(tmp_path / 'processed.json')):
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
    article.query_selector.return_value.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []
    
    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate') as mock_translate:
        mock_translate.return_value = "Translated Content"
        
        process_article_content(playwright, browser, context, article)
        
        # Verify notifications were sent
        assert mock_notify.call_count == 2
        assert mock_translate.call_count == 2

def test_load_processed_articles_error(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE', str(tmp_path / 'processed.json')):
        # Test invalid JSON file
        with open(tmp_path / 'processed.json', 'w') as f:
            f.write('invalid json')
        assert load_processed_articles() == []

def test_save_processed_article_error(tmp_path):
    with patch('get_social_schools_news.PROCESSED_ARTICLES_FILE', str(tmp_path / 'processed.json')):
        # Test file permission error
        with patch('builtins.open', side_effect=PermissionError):
            assert save_processed_article("article1") is False

def test_translate_error(mock_config):
    with patch('deep_translator.GoogleTranslator.translate', side_effect=Exception("Translation failed")):
        with pytest.raises(Exception):
            translate("Original text")

def test_send_notification_error(mock_config):
    with patch('requests.post', side_effect=Exception("Network error")):
        send_notification("Test Title", "Test Body", "test_key")  # Should not raise exception

def test_process_article_content_error(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright
    
    # Mock article with missing content
    article = Mock()
    article.query_selector.return_value = None
    
    with pytest.raises(AttributeError):
        process_article_content(playwright, browser, context, article)

def test_process_article_content_missing_attachments(mock_playwright, mock_config):
    playwright, browser, context, page = mock_playwright
    
    # Mock article with content but no attachments
    article = Mock()
    article.query_selector.return_value.inner_text.return_value = "Test Content"
    article.query_selector_all.return_value = []
    
    with patch('get_social_schools_news.send_notification') as mock_notify, \
         patch('get_social_schools_news.translate') as mock_translate:
        mock_translate.return_value = "Translated Content"
        
        process_article_content(playwright, browser, context, article)
        
        # Verify only article content notifications were sent
        assert mock_notify.call_count == 2
        assert mock_translate.call_count == 2 
