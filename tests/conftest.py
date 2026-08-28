"""Fixtures every test in this suite can rely on.

The suite must never touch the real `var/` tree, the real config, or the
network. `SOCIALSCHOOLS_VAR` is redirected at import time — before any test
module imports the package — so every path constant resolves under a throwaway
directory. A test that forgets to patch something writes into the sandbox
rather than over the developer's own data.
"""
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

# conftest is imported before any test module, which is the only moment early
# enough for socialschools.paths to see this.
_VAR_TREE = tempfile.TemporaryDirectory()
os.environ["SOCIALSCHOOLS_VAR"] = _VAR_TREE.name


@pytest.fixture(scope="session", autouse=True)
def var_tree():
    """The throwaway var/ root, cleaned up when the session ends."""
    yield _VAR_TREE.name
    _VAR_TREE.cleanup()


@pytest.fixture
def test_config():
    """A Config with invented credentials. Never real ones — this repo is public."""
    from socialschools.config import Config
    return Config(
        SCRAPED_WEBSITE_USER="test_user@example.com",
        SCRAPED_WEBSITE_PASSWORD="test_password",
        PUSHBULLET_API_KEYS="Test:test_api_key",
        TRANSLATION_LANGUAGE="en",
        DIGEST_ENABLED=True,
    )


@pytest.fixture(autouse=True)
def mock_config(test_config):
    """Every test runs against the invented Config, with caches cleared around it."""
    from socialschools import config as config_module
    from socialschools import translate as translate_module

    config_module.reset_config()
    translate_module._cache.clear()
    with patch.object(config_module, "load_config", return_value=test_config):
        yield test_config
    config_module.reset_config()


@pytest.fixture
def mock_playwright():
    """A Playwright stack of Mocks: (playwright, browser, context, page)."""
    playwright = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()

    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page

    return playwright, browser, context, page
