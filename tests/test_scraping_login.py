from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from socialschools.config import Config
from socialschools.scraping.login import login_to_website


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

    with patch('socialschools.scraping.login.get_config') as mock_get_config:
        mock_get_config.return_value = Config(
            SCRAPED_WEBSITE_USER="test@example.com",
            SCRAPED_WEBSITE_PASSWORD="testpass",
            PUSHBULLET_API_KEYS="Test:testkey"
        )

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
