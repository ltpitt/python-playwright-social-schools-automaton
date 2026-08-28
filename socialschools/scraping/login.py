"""Signing in to Social Schools.

The application redirects to a separate authentication host after its shell
loads, so waiting for network idle can finish before that asynchronous redirect
on a slower device such as a Raspberry Pi. Every wait is therefore explicit and
generous, and every timeout says which step and which URL it gave up on.
"""
import logging
import traceback

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..config import get_config

logger = logging.getLogger(__name__)

HOME_URL = "https://app.socialschools.eu/home"
WAIT_MS = 60000


def login_to_website(page):
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded")

        username_field = page.locator("#username")
        try:
            username_field.wait_for(state="visible", timeout=WAIT_MS)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Username field not found after waiting for the login page (URL: {page.url})"
            ) from error
        username_field.fill(get_config().SCRAPED_WEBSITE_USER)

        password_field = page.locator("#Password")
        try:
            password_field.wait_for(state="visible", timeout=WAIT_MS)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Password field not found after waiting for the login page (URL: {page.url})"
            ) from error
        password_field.fill(get_config().SCRAPED_WEBSITE_PASSWORD)

        password_field.press("Enter")

        try:
            page.wait_for_url(f"{HOME_URL}**", wait_until="domcontentloaded", timeout=WAIT_MS)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Login did not return to the Social Schools home page (URL: {page.url})"
            ) from error
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise
