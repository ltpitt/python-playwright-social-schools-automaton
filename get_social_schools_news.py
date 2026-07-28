import argparse
import os
import re
import subprocess
import pycurl
import logging
import traceback
from io import BytesIO
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import fitz  # PyMuPDF
import requests
from deep_translator import GoogleTranslator
import json
from docx import Document
from dataclasses import dataclass
import configparser
import tempfile


def resolve_browser_executable_path():
    env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates = [
        env_path,
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


@dataclass
class Config:
    SCRAPED_WEBSITE_USER: str
    SCRAPED_WEBSITE_PASSWORD: str
    PUSHBULLET_API_KEY: str
    TRANSLATION_LANGUAGE: str = "en"
    DIGEST_ENABLED: bool = True
    PUSHBULLET_CHANNEL_TAG: str = ""


@dataclass
class Digest:
    translated_title: str
    tldr: str
    action_items: list
    key_dates: list


@dataclass
class Attachment:
    filename: str
    url: str
    filetype: str   # "pdf" or "docx"
    text: str
    failed: bool = False


def load_config() -> Config:
    # Try user's config first, then fall back to example config
    config_file = 'config.ini' if os.path.exists('config.ini') else 'config.example.ini'
    config = configparser.ConfigParser()
    config.read(config_file)

    return Config(
        SCRAPED_WEBSITE_USER=config['DEFAULT']['SCRAPED_WEBSITE_USER'],
        SCRAPED_WEBSITE_PASSWORD=config['DEFAULT']['SCRAPED_WEBSITE_PASSWORD'],
        PUSHBULLET_API_KEY=config['DEFAULT']['PUSHBULLET_API_KEY'],
        TRANSLATION_LANGUAGE=config['DEFAULT'].get('TRANSLATION_LANGUAGE', 'en'),
        DIGEST_ENABLED=config['DEFAULT'].get('DIGEST_ENABLED', 'true').strip().lower() == 'true',
        PUSHBULLET_CHANNEL_TAG=config['DEFAULT'].get('PUSHBULLET_CHANNEL_TAG', '').strip(),
    )


config = None
FORCE_REPROCESS = False


def get_config() -> Config:
    global config
    if config is None:
        config = load_config()
    return config


logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logging
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("run_report.txt", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)

PROCESSED_ARTICLES_FILE = "processed_articles.json"

DIGEST_PROMPT_TEMPLATE = (
    "You are writing a brief for a busy parent. Turn the Dutch school message "
    "below into a structured JSON object.\n\n"
    "Respond with ONLY a valid JSON object. No markdown fences, no explanation.\n\n"
    "Required structure:\n"
    "{{\n"
    "  \"translated_title\": \"<article title in {language}>\",\n"
    "  \"tldr\": \"<1-3 sentence summary in {language}, empty string if "
    "action_items and key_dates cover everything>\",\n"
    "  \"action_items\": [\"<deadline first - what parent must do>\"],\n"
    "  \"key_dates\": [\"<date - event or closure>\"]\n"
    "}}\n\n"
    "Rules:\n"
    "- action_items and key_dates are empty arrays [] if none exist.\n"
    "- action_items: things the parent must actively do. Format: 'DD Mon - what to do'\n"
    "- key_dates: informational events or closures the parent does not need to act on. Format: 'DD Mon - event'\n"
    "- Do NOT repeat a date in key_dates if it already appears in action_items.\n"
    "- All text values in {language}.\n"
    "- Output ONLY the JSON object, nothing else.\n\n"
    "--- MESSAGE START ---\n"
    "Title: {title}\n\n"
    "{body}{attachments}\n"
    "--- MESSAGE END ---"
)

REQUIRED_DIGEST_FIELDS = {"translated_title", "tldr", "action_items", "key_dates"}


def load_processed_articles():
    try:
        if os.path.exists(PROCESSED_ARTICLES_FILE):
            with open(PROCESSED_ARTICLES_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"Error loading processed articles: {e}")
        return []


def save_processed_article(article_id):
    try:
        processed = load_processed_articles()
        if article_id not in processed:
            processed.append(article_id)
            with open(PROCESSED_ARTICLES_FILE, 'w') as f:
                json.dump(processed, f)
            return True
        return False
    except Exception as e:
        logger.error(f"Error saving processed article: {e}")
        return False


def download_pdf(url, output_path):
    logger.info(f"Starting download of PDF from {url}")
    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.WRITEDATA, buffer)
    c.perform()
    c.close()

    with open(output_path, "wb") as f:
        f.write(buffer.getvalue())
    logger.info(f"PDF downloaded and saved to {output_path}")


def _download_pdf(url, output_path, browser_context=None):
    """Download a PDF. Uses the authenticated Playwright session when available."""
    if browser_context is not None:
        logger.info(f"Downloading PDF from {url} (authenticated session)")
        resp = browser_context.request.get(url)
        if not resp.ok:
            raise IOError(f"Authenticated PDF download failed ({resp.status}): {url}")
        with open(output_path, "wb") as f:
            f.write(resp.body())
        logger.info(f"PDF downloaded to {output_path}")
        return
    logger.info(f"Downloading PDF from {url}")
    response = requests.get(url, timeout=30, stream=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"PDF downloaded to {output_path}")


def _download_docx(url, output_path, browser_context=None):
    """Download a DOCX. Uses the authenticated Playwright session when available."""
    if browser_context is not None:
        logger.info(f"Downloading DOCX from {url} (authenticated session)")
        resp = browser_context.request.get(url)
        if not resp.ok:
            raise IOError(f"Authenticated DOCX download failed ({resp.status}): {url}")
        with open(output_path, "wb") as f:
            f.write(resp.body())
        logger.info(f"DOCX downloaded to {output_path}")
        return
    logger.info(f"Downloading DOCX from {url}")
    response = requests.get(url, timeout=30, stream=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"DOCX downloaded to {output_path}")


def extract_text(pdf_path):
    logger.info(f"Extracting text from PDF {pdf_path}")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    logger.info(f"Text extraction complete for {pdf_path}")
    return text


def translate(text, src="nl", dest=None, chunk_size=4900):
    if dest is None:
        dest = get_config().TRANSLATION_LANGUAGE
    logger.info(f"Translating text from {src} to {dest}")
    translator = GoogleTranslator(source=src, target=dest)
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    translated_chunks = [translator.translate(chunk) for chunk in chunks]
    logger.info("Translation complete")
    return " ".join(translated_chunks)


def send_notification(title, body, api_key=None, channel_tag=None):
    if api_key is None:
        api_key = get_config().PUSHBULLET_API_KEY
    if channel_tag is None:
        channel_tag = get_config().PUSHBULLET_CHANNEL_TAG
    logger.info(f"Sending Pushbullet notification with title: {title}")
    logger.debug(f"Notification body:\n{body}")
    params = {"type": "note", "title": title, "body": body}
    if channel_tag:
        params["channel_tag"] = channel_tag
    response = requests.post(
        "https://api.pushbullet.com/v2/pushes",
        data=json.dumps(params),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    logger.info("Pushbullet notification sent")


def _check_copilot_available():
    """Fail fast if the Copilot CLI is not reachable before processing any Article."""
    try:
        result = subprocess.run(
            ["copilot", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError("Copilot CLI not found. Ensure 'copilot' is in PATH.")
    if result.returncode != 0:
        raise RuntimeError(f"Copilot CLI health check failed (code {result.returncode})")


# Per ADR 0001: non-interactive invocation via -p flag.
# Per ADR 0002: the -p flag enforces no tool access. Never add --tool flags to this tuple.
_COPILOT_TOOL_FREE_ARGS = ("copilot", "--no-color")

# ADR 0002 guard: fail at import time if tool-access flags drift into this constant.
assert not any("--tool" in arg for arg in _COPILOT_TOOL_FREE_ARGS), (
    "ADR 0002 violation: _COPILOT_TOOL_FREE_ARGS must not contain --tool flags"
)


def _run_copilot(prompt):
    try:
        result = subprocess.run(
            [*_COPILOT_TOOL_FREE_ARGS, "-p", prompt],
            # Note: --no-color already in _COPILOT_TOOL_FREE_ARGS; -p disables tool access (ADR 0002)
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError("Copilot CLI not found. Ensure 'copilot' is in PATH.")
    if result.returncode != 0:
        logger.error(f"Copilot CLI stderr:\n{result.stderr}")
        raise RuntimeError(f"Copilot CLI returned code {result.returncode}")
    return result.stdout.strip()


def _extract_json(text):
    # 1. Clean parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Markdown-fenced JSON block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. Scan forward and use raw_decode to find the first VALID JSON object
    #    (avoids greedy-regex failures when Copilot wraps JSON in prose)
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find('{', idx)
        if start == -1:
            break
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            idx = start + 1
    raise ValueError("No valid JSON found in response")


def _dict_to_digest(data: dict) -> Digest:
    """Validate a raw JSON dict and convert it to a typed Digest. Raises ValueError on bad shape."""
    missing = REQUIRED_DIGEST_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    if not isinstance(data.get("translated_title"), str) or not data["translated_title"].strip():
        raise ValueError("'translated_title' must be a non-empty string")
    if not isinstance(data.get("tldr"), str):
        raise ValueError("'tldr' must be a string")
    for field in ("action_items", "key_dates"):
        if not isinstance(data[field], list):
            raise ValueError(f"Field '{field}' must be a list")
    return Digest(
        translated_title=data["translated_title"],
        tldr=data["tldr"],
        action_items=list(dict.fromkeys(data["action_items"])),
        key_dates=list(dict.fromkeys(data["key_dates"])),
    )


def _get_article_id(article):
    article_id = article.get_attribute("data-id") or article.get_attribute("id")
    if not article_id:
        logger.debug("No article ID attribute, generating from title and timestamp")
        title_el = article.query_selector("h3")
        title = title_el.inner_text() if title_el else "unknown"
        timestamp_el = article.query_selector("time")
        timestamp = (timestamp_el.get_attribute("datetime")
                     if timestamp_el else datetime.now().isoformat())
        article_id = f"{title}_{timestamp}"
        logger.info(f"Generated article ID: {article_id}")
    return article_id


def _get_post_date(article):
    """Return the post's date as 'D Mon' (e.g. '1 Jul'), or None if unavailable."""
    time_el = article.query_selector("time")
    if not time_el:
        return None
    raw = time_el.get_attribute("datetime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).strftime("%-d %b")
    except (ValueError, TypeError):
        return None


def render_digest_notification(data: Digest, failed_attachments=None, original_title=None, post_date=None):
    sections = []

    tldr = data.tldr.strip()
    if tldr:
        sections.append(tldr)

    if data.action_items:
        action_block = "Action Items:\n" + "\n".join(f"\u25b8 {item}" for item in data.action_items)
        sections.append(action_block)

    if data.key_dates:
        dates_block = "Key Dates:\n" + "\n".join(f"\u25b8 {d}" for d in data.key_dates)
        sections.append(dates_block)

    if not data.action_items and not data.key_dates:
        sections.append("No action needed")

    if failed_attachments:
        sections.append("\u26a0 An attachment could not be read \u2014 check the original post for complete info")

    if original_title:
        when = f" ({post_date})" if post_date else ""
        sections.append(f"To find this post in Social Schools, look for: \"{original_title}\"{when}")

    return "\n\n".join(sections)


def generate_digest(title, body, attachments):
    language = get_config().TRANSLATION_LANGUAGE
    attachment_text = ""
    if attachments:
        parts = [f"\n\n[Attachment: {a.filename}]\n{a.text}" for a in attachments if not a.failed]
        failed_parts = [f"\n\n[Attachment: {a.filename} \u2014 could not be extracted]" for a in attachments if a.failed]
        attachment_text = "".join(parts + failed_parts)

    prompt = DIGEST_PROMPT_TEMPLATE.format(
        language=language,
        title=title,
        body=body,
        attachments=attachment_text,
    )

    logger.info("Generating Digest via Copilot CLI")
    raw = _run_copilot(prompt)
    logger.debug(f"Copilot raw response:\n{raw}")

    try:
        digest = _dict_to_digest(_extract_json(raw))
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Digest response invalid ({e}), retrying once")
        retry_prompt = (
            "The previous response was not valid JSON or was missing required fields. "
            "Respond with ONLY this JSON structure (no markdown, no explanation):\n"
            '{\n  "translated_title": "...",\n  "tldr": "...",\n'
            '  "action_items": [...],\n  "key_dates": [...]\n}\n\n'
            f"Previous invalid response:\n{raw}\n\n"
            f"Original prompt:\n{prompt}"
        )
        raw = _run_copilot(retry_prompt)
        try:
            digest = _dict_to_digest(_extract_json(raw))
        except (ValueError, json.JSONDecodeError) as e2:
            logger.warning(f"Digest retry also invalid ({e2}), using safe fallback")
            digest = Digest(
                translated_title=title,
                tldr="(Could not generate summary \u2014 open the original post for details)",
                action_items=[],
                key_dates=[],
            )

    logger.info("Digest validated successfully")

    return digest


def process_pdf_links(playwright, browser, context, pdf_links):
    attachments = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for link in pdf_links:
            pdf_url = link.get_attribute("href")
            pdf_filename = pdf_url.split("/")[-1].split("?")[0]
            pdf_path = os.path.join(temp_dir, pdf_filename)
            try:
                _download_pdf(pdf_url, pdf_path, browser_context=context)
                text = extract_text(pdf_path)
                attachments.append(Attachment(filename=pdf_filename, url=pdf_url, filetype="pdf", text=text))
            except Exception as e:
                logger.error(f"Failed to process PDF '{pdf_filename}': {e}")
                attachments.append(Attachment(filename=pdf_filename, url=pdf_url, filetype="pdf", text="", failed=True))
    return attachments


def extract_text_from_docx(docx_path):
    logger.info(f"Extracting text from Word document {docx_path}")
    doc = Document(docx_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    logger.info(f"Text extraction complete for {docx_path}")
    return text


def process_docx_links(playwright, browser, context, docx_links):
    attachments = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for link in docx_links:
            docx_url = link.get_attribute("href")
            docx_filename = docx_url.split("/")[-1].split("?")[0]
            docx_path = os.path.join(temp_dir, docx_filename)
            try:
                _download_docx(docx_url, docx_path, browser_context=context)
                text = extract_text_from_docx(docx_path)
                attachments.append(Attachment(filename=docx_filename, url=docx_url, filetype="docx", text=text))
            except Exception as e:
                logger.error(f"Failed to process DOCX '{docx_filename}': {e}")
                attachments.append(Attachment(filename=docx_filename, url=docx_url, filetype="docx", text="", failed=True))
    return attachments


def run(playwright):
    try:
        launch_options = {"headless": True}
        executable_path = resolve_browser_executable_path()
        if executable_path:
            launch_options["executable_path"] = executable_path
            logger.info(f"Using browser executable: {executable_path}")
        else:
            logger.info("No system browser executable found, using Playwright default Chromium")

        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context()
        page = context.new_page()

        login_to_website(page)

        if "home" in page.url:
            if get_config().DIGEST_ENABLED:
                _check_copilot_available()
            process_all_articles(playwright, browser, context, page)
        else:
            raise Exception("Login failed - URL does not contain 'home'")

        browser.close()
    except Exception as e:
        logger.error(f"Error in main run function: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def login_to_website(page):
    try:
        page.goto("https://app.socialschools.eu/home")
        page.wait_for_load_state("networkidle")

        username_field = page.locator("#username")
        if not username_field.is_visible():
            raise Exception("Username field not found")
        page.fill("#username", get_config().SCRAPED_WEBSITE_USER)

        password_field = page.locator("#Password")
        if not password_field.is_visible():
            raise Exception("Password field not found")
        page.fill("#Password", get_config().SCRAPED_WEBSITE_PASSWORD)

        page.press("#Password", "Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            raise
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def process_all_articles(playwright, browser, context, page):
    try:
        logger.debug("Looking for feed element")
        feed = page.query_selector("div[role='feed']")
        if not feed:
            logger.error("Feed element not found")
            raise Exception("Feed element not found")
        logger.debug("Feed element found")

        articles = feed.query_selector_all("div[role='article']")
        if not articles:
            logger.warning("No articles found in feed")
            return
        logger.info(f"Found {len(articles)} article(s) in feed")

        processed_ids = load_processed_articles()

        for article in articles:
            article_id = _get_article_id(article)
            title_el = article.query_selector("h3")
            title = title_el.inner_text() if title_el else "(no title)"
            logger.info(f"Checking article: {title} [{article_id}]")

            if not FORCE_REPROCESS and article_id in processed_ids:
                logger.info(f"Article {article_id} already processed, skipping")
                continue

            if FORCE_REPROCESS:
                logger.info(f"Force mode active: processing article {article_id} without updating state")
            else:
                logger.info(f"Processing new article: {article_id}")

            expand_full_text(article)

            try:
                process_article_content(playwright, browser, context, article)
                if not FORCE_REPROCESS:
                    save_processed_article(article_id)
                    processed_ids.append(article_id)
            except Exception as e:
                logger.error(f"Error processing article {article_id}: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                # Continue to next article; leave unmarked for retry

    except Exception as e:
        logger.error(f"Error in process_all_articles: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def expand_full_text(article):
    try:
        more_button = article.query_selector("button:has-text('Meer weergeven')")
        if more_button:
            more_button.click()

        article.wait_for_selector("span[as='div']")
    except Exception as e:
        logger.error(f"Error expanding full text: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def process_article_content(playwright, browser, context, article):
    body = article.query_selector("span[as='div']").inner_text()
    title = article.query_selector("h3").inner_text()

    if not get_config().DIGEST_ENABLED:
        # Translation-only mode: no LLM, no attachment extraction
        logger.info("Digest disabled — sending translated content directly")
        send_notification(title=translate(title), body=translate(body))
        return

    attachments = []  # list[Attachment] — includes failed extractions

    # Diagnostic: log all article hrefs for runtime observability of attachment formats
    all_links = article.query_selector_all("a[href]")
    if all_links:
        hrefs = [link.get_attribute("href") for link in all_links if link.get_attribute("href")]
        if hrefs:
            logger.debug(f"Article links ({len(hrefs)}): {[h.split('?')[0] for h in hrefs]}")

    pdf_links = article.query_selector_all("a[href*='.pdf']")
    if pdf_links:
        attachments.extend(process_pdf_links(playwright, browser, context, pdf_links))

    docx_links = article.query_selector_all("a[href*='.docx']")
    if docx_links:
        attachments.extend(process_docx_links(playwright, browser, context, docx_links))

    if not pdf_links and not docx_links:
        logger.info("No PDFs or Word documents found in article.")

    try:
        data = generate_digest(title, body, attachments)
    except RuntimeError as e:
        logger.error(f"Digest generation failed: {e}")
        send_notification(
            title="Social Schools update",
            body="Could not generate Digest for the latest article. Will retry on next run.",
        )
        raise

    failed_names = [a.filename for a in attachments if a.failed] or None
    send_notification(
        title=data.translated_title,
        body=render_digest_notification(
            data,
            failed_attachments=failed_names,
            original_title=title,
            post_date=_get_post_date(article),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Social Schools news automation")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process the first article even if already seen, without updating state",
    )
    args = parser.parse_args()
    FORCE_REPROCESS = args.force
    try:
        with sync_playwright() as playwright:
            run(playwright)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise
