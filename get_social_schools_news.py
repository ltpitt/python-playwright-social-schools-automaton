import argparse
import glob
import os
import re
import shutil
import smtplib
import subprocess
import time
import pycurl
import logging
import traceback
from email.message import EmailMessage
from io import BytesIO
from datetime import date, datetime, timedelta
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
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]

    for browser_name in (
        "chromium-browser",
        "chromium",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ):
        resolved = shutil.which(browser_name)
        if resolved:
            candidates.append(resolved)

    for playwright_root in (
        os.path.expanduser("~/.cache/ms-playwright"),
        os.path.expanduser("~/.local/share/ms-playwright"),
    ):
        if os.path.isdir(playwright_root):
            candidates.extend(
                glob.glob(os.path.join(playwright_root, "**", "chrome-linux", "chrome"), recursive=True)
            )
            candidates.extend(
                glob.glob(os.path.join(playwright_root, "**", "chrome-linux", "chrome.exe"), recursive=True)
            )

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


@dataclass
class Config:
    SCRAPED_WEBSITE_USER: str
    SCRAPED_WEBSITE_PASSWORD: str
    # Comma-separated 'name:token[:language]' pairs, one per Pushbullet
    # recipient (e.g. "Davide:o.abc123:it,Daniela:o.xyz789:en"). Works for a
    # single recipient too ("Me:o.abc123"). Each token is a private,
    # per-person Pushbullet access token, so only people you explicitly list
    # here ever receive anything, and the name lets logs identify who a push
    # went to. The optional trailing ':language' overrides TRANSLATION_LANGUAGE
    # for that recipient only; omit it to use TRANSLATION_LANGUAGE. Leave
    # empty to disable Pushbullet and rely solely on email notifications.
    PUSHBULLET_API_KEYS: str = ""
    TRANSLATION_LANGUAGE: str = "en"
    # Email notifications via Gmail SMTP. Leave EMAIL_RECIPIENTS empty to
    # disable email entirely. When set, EMAIL_SENDER and EMAIL_APP_PASSWORD
    # must both be provided (the app password is a Gmail App Password, not the
    # account's normal password). EMAIL_RECIPIENTS is a comma-separated list of
    # 'name:email[:language]' pairs, mirroring PUSHBULLET_API_KEYS; each
    # recipient is emailed individually so their address is never exposed to
    # the others.
    EMAIL_SENDER: str = ""
    EMAIL_APP_PASSWORD: str = ""
    EMAIL_RECIPIENTS: str = ""
    # Admin channel: receives every error/problem the run hits, including ones
    # that are invisible to parents (login failures, attachment extraction
    # errors, degraded digests). Both are optional and independent; leave both
    # empty to disable admin alerting. ADMIN_EMAIL reuses EMAIL_SENDER /
    # EMAIL_APP_PASSWORD for delivery.
    ADMIN_PUSHBULLET_API_KEY: str = ""
    ADMIN_EMAIL: str = ""
    DIGEST_ENABLED: bool = True
    # LLM backend used to generate a Digest. Only consulted when DIGEST_ENABLED
    # is true; Translation mode never touches any of these.
    #   "copilot"            -> the GitHub Copilot CLI (default, ADR 0001)
    #   "openai_compatible"  -> any OpenAI-compatible /chat/completions endpoint
    #                           (local Ollama, OpenRouter, and most cloud providers)
    LLM_PROVIDER: str = "copilot"
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""
    LLM_TIMEOUT: int = 120
    # Extra thinking budget for models that support it ("low"/"medium"/"high").
    # Empty means don't ask for any, which is what non-reasoning models need.
    LLM_REASONING_EFFORT: str = ""
    # Ask the endpoint to enforce the Digest JSON schema server-side. Falls back
    # automatically when the endpoint rejects it, so it is safe to leave on.
    LLM_STRUCTURED_OUTPUT: bool = True


@dataclass
class Topic:
    """One subject within a message, mirroring how the school actually organised it."""
    heading: str
    actions: list
    bring: list
    notes: list


@dataclass
class Digest:
    translated_title: str
    tldr: str
    topics: list


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
        PUSHBULLET_API_KEYS=config['DEFAULT'].get('PUSHBULLET_API_KEYS', '').strip(),
        EMAIL_SENDER=config['DEFAULT'].get('EMAIL_SENDER', '').strip(),
        EMAIL_APP_PASSWORD=config['DEFAULT'].get('EMAIL_APP_PASSWORD', '').strip(),
        EMAIL_RECIPIENTS=config['DEFAULT'].get('EMAIL_RECIPIENTS', '').strip(),
        ADMIN_PUSHBULLET_API_KEY=config['DEFAULT'].get('ADMIN_PUSHBULLET_API_KEY', '').strip(),
        ADMIN_EMAIL=config['DEFAULT'].get('ADMIN_EMAIL', '').strip(),
        TRANSLATION_LANGUAGE=config['DEFAULT'].get('TRANSLATION_LANGUAGE', 'en'),
        DIGEST_ENABLED=config['DEFAULT'].get('DIGEST_ENABLED', 'true').strip().lower() == 'true',
        LLM_PROVIDER=config['DEFAULT'].get('LLM_PROVIDER', 'copilot').strip().lower(),
        LLM_BASE_URL=config['DEFAULT'].get('LLM_BASE_URL', '').strip(),
        LLM_MODEL=config['DEFAULT'].get('LLM_MODEL', '').strip(),
        LLM_API_KEY=config['DEFAULT'].get('LLM_API_KEY', '').strip(),
        LLM_TIMEOUT=int(config['DEFAULT'].get('LLM_TIMEOUT', '120').strip() or '120'),
        LLM_REASONING_EFFORT=config['DEFAULT'].get('LLM_REASONING_EFFORT', '').strip().lower(),
        LLM_STRUCTURED_OUTPUT=config['DEFAULT'].get(
            'LLM_STRUCTURED_OUTPUT', 'true').strip().lower() == 'true',
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

# Gmail SMTP over implicit TLS; we assume Gmail as the sending provider.
EMAIL_SMTP_HOST = "smtp.gmail.com"
EMAIL_SMTP_PORT = 465

DIGEST_PROMPT_TEMPLATE = (
    "You are writing a brief for a busy parent. Turn the Dutch school message "
    "below into a structured JSON object.\n\n"
    "Respond with ONLY a valid JSON object. No markdown fences, no explanation.\n\n"
    "Required structure:\n"
    "{{\n"
    "  \"translated_title\": \"<article title in {language}>\",\n"
    "  \"tldr\": \"<one sentence in {language} giving the substance: the soonest thing to do "
    "or know, with its date>\",\n"
    "  \"topics\": [\n"
    "    {{\n"
    "      \"heading\": \"<short subject of this part of the message, in {language}>\",\n"
    "      \"actions\": [\"<something the parent must do or arrange>\"],\n"
    "      \"bring\": [\"<one physical item the child must be given or take along>\"],\n"
    "      \"notes\": [\"<something to be aware of that needs no action>\"]\n"
    "    }}\n"
    "  ]\n"
    "}}\n\n"
    "Rules:\n"
    "- Group the message into topics mirroring how it is actually organised (its own headings or "
    "paragraph subjects). Most messages have 1-3 topics; use a single topic when the message covers "
    "only one subject. Never split one subject across several topics.\n"
    "- bring: physical things to provide or pack, ONE item per entry, named exactly as in the "
    "message. Never repeat the same item's full description in actions. If the parent must buy "
    "or provide it, put the item in 'bring' and make the action generic, e.g. 'Purchase the "
    "item for group 3'.\n"
    "- actions: what the parent must actively do or arrange. notes: facts that need no action. "
    "If the reader must be somewhere at a time, or must do or send something, it is an action "
    "even when the message states it as a fact. Never leave an arrival time, a hand-in time or "
    "an instruction in notes.\n"
    "- actions, bring and notes are each an empty array [] when that topic has none.\n"
    "- Use at most ONE entry per real-world event within a topic. Gather every fact about that "
    "event - arrival time, departure time, destination, return time and any related instruction "
    "- into that single entry. For example, a school trip becomes one entry like '01 Sep - Trip "
    "to the polder: arrive 08:20, bus departs 08:30, returns around 14:30 (may be later)', never "
    "several lines each restating one time. Never put the same event's facts in both an action "
    "and a note.\n"
    "- Prefix an entry with 'DD Mon - ' ONLY when the message states a date for it, always with a "
    "zero-padded two-digit day: '07 Sep', never '7 Sep'. If there is no "
    "date, write the entry without any date prefix. NEVER invent a date or use a placeholder like "
    "'XX Sep' or 'date not specified'. If the source gives only a weekday, keep the entry "
    "undated rather than writing '(date not specified)' anywhere.\n"
    "- Order topics by urgency: soonest date first, undated topics last.\n"
    "- Format every clock time as 24-hour HH:MM, zero-padded (e.g. '08:30', '14:30'). Never use "
    "12-hour AM/PM \u2014 the notification's own post-date header is already 24-hour, and a mixed "
    "message is harder to scan.\n"
    "- Say which group or class an entry applies to whenever the message specifies one. When the "
    "message singles out particular groups (e.g. asks 6B and 6C for something), name each of those "
    "groups explicitly in the entry rather than generalising to 'some groups'.\n"
    "- A request for parents to volunteer or help (e.g. accompanying a trip, driving, joining a "
    "committee) is important even though it is optional. Keep it, and keep the number of people "
    "asked for and any per-group detail, e.g. 'two parents per group needed to join the trip'.\n"
    "- Every obligation in the message MUST appear somewhere, dated or not \u2014 use the pre-scan "
    "hints below (if any) so you don't miss one, but never invent an item that isn't actually in "
    "the message.\n"
    "- Each entry must be specific enough to act on without opening the original message.\n"
    "- If an entry is based on information found in an attachment rather than the "
    "article body itself, append the source attachment's filename in parentheses at the end, e.g. "
    "'DD Mon - what to do (see filename.pdf)'.\n"
    "- tldr must never be empty, and must state the substance rather than describe the message. "
    "A parent who reads only this line should already know the most important thing. Write "
    "'School trip on 01 Sep: pack a raincoat and a packed lunch', never "
    "'This message provides important information about the school trip and upcoming tests'.\n"
    "- All text values in {language}.\n"
    "- Output ONLY the JSON object, nothing else.\n\n"
    "--- MESSAGE START ---\n"
    "Title: {title}\n\n"
    "{body}{attachments}\n"
    "--- MESSAGE END ---"
    "{hints}"
)

REQUIRED_DIGEST_FIELDS = {"translated_title", "tldr", "topics"}

# The same contract as DIGEST_PROMPT_TEMPLATE's example, in a form an endpoint
# can enforce. Prompt wording alone cannot stop a model emitting prose around
# the JSON; a schema can, which removes a whole class of parse failures.
_ENTRY_LIST_SCHEMA = {"type": "array", "items": {"type": "string"}}
DIGEST_JSON_SCHEMA = {
    "name": "digest",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["translated_title", "tldr", "topics"],
        "properties": {
            "translated_title": {"type": "string"},
            "tldr": {"type": "string"},
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["heading", "actions", "bring", "notes"],
                    "properties": {
                        "heading": {"type": "string"},
                        "actions": _ENTRY_LIST_SCHEMA,
                        "bring": _ENTRY_LIST_SCHEMA,
                        "notes": _ENTRY_LIST_SCHEMA,
                    },
                },
            },
        },
    },
}

_DATE_HINT_RE = re.compile(
    r'\b\d{1,2}\s*(?:jan|feb|mrt|maart|apr|mei|jun(?:i)?|jul(?:i)?|aug|sep|okt|nov|dec)[a-z]*\.?',
    re.IGNORECASE,
)
_TIME_HINT_RE = re.compile(r'\b([01]?\d|2[0-3])[:.][0-5]\d\b')
_IMPERATIVE_HINT_RE = re.compile(
    r'\b(graag|gelieve|zorg dat|vergeet niet|lever .{0,20}in|meenemen|inleveren|aanmeld\w*|betaal\w*|onderteken\w*)',
    re.IGNORECASE,
)

# Social Schools renders a post's date/time as Dutch text (e.g. "7 juli om 13:19") rather than a
# machine-readable <time> element. Map full Dutch month names to English abbreviations so
# _get_post_date can parse that text directly.
_DUTCH_MONTHS = {
    "januari": "Jan", "februari": "Feb", "maart": "Mar", "april": "Apr",
    "mei": "May", "juni": "Jun", "juli": "Jul", "augustus": "Aug",
    "september": "Sep", "oktober": "Oct", "november": "Nov", "december": "Dec",
}
_POST_DATETIME_RE = re.compile(
    r'(\d{1,2})\s+(' + "|".join(_DUTCH_MONTHS) + r')\b(?:[^\d]{0,6}(\d{1,2}:\d{2}))?',
    re.IGNORECASE,
)

# Recent posts are labelled relatively ("vandaag om 15:47", "afgelopen dinsdag om 15:39") and only
# older ones carry a month name, so relative labels must be resolved against the current date.
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_RELATIVE_DAY_OFFSETS = {"vandaag": 0, "gisteren": 1, "eergisteren": 2}
_RELATIVE_DAY_RE = re.compile(
    r'\b(' + "|".join(_RELATIVE_DAY_OFFSETS) + r')\b', re.IGNORECASE)
_DUTCH_WEEKDAYS = {
    "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3,
    "vrijdag": 4, "zaterdag": 5, "zondag": 6,
}
_WEEKDAY_RE = re.compile(r'\b(' + "|".join(_DUTCH_WEEKDAYS) + r')\b', re.IGNORECASE)
_TIME_OF_DAY_RE = re.compile(r'\b(\d{1,2}:\d{2})\b')


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
        notify_admin("Could not persist processed article state", f"Article: {article_id}", exc=e)
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


_translation_cache = {}


def translate(text, src="nl", dest=None, chunk_size=4900):
    if dest is None:
        dest = get_config().TRANSLATION_LANGUAGE
    cache_key = (text, src, dest)
    if cache_key in _translation_cache:
        logger.debug(f"Translation cache hit ({src} -> {dest}); reusing previous result")
        return _translation_cache[cache_key]
    logger.info(f"Translating text from {src} to {dest}")
    translator = GoogleTranslator(source=src, target=dest)
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    translated_chunks = [translator.translate(chunk) for chunk in chunks]
    logger.info("Translation complete")
    result = " ".join(translated_chunks)
    _translation_cache[cache_key] = result
    return result


@dataclass
class Recipient:
    value: str  # Pushbullet token or email address
    language: str


def _parse_recipients(raw, field_name="PUSHBULLET_API_KEYS", default_language=None):
    """Parse a comma-separated 'name:value[:language]' string into {name: Recipient}.

    Used for both PUSHBULLET_API_KEYS (name:token[:language]) and
    EMAIL_RECIPIENTS (name:email[:language]). The trailing ':language' is
    optional and defaults to TRANSLATION_LANGUAGE, so existing 'name:value'
    entries keep working unchanged. Raises ValueError if an entry is missing
    the ':' separator or has an empty name/value/language, so misconfiguration
    is caught early instead of silently dropping a recipient.
    """
    if default_language is None:
        default_language = get_config().TRANSLATION_LANGUAGE
    parsed = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) == 2:
            name, value = parts
            language = default_language
        elif len(parts) == 3:
            name, value, language = parts
        else:
            raise ValueError(
                f"Invalid {field_name} entry {entry!r}; expected 'name:value' or 'name:value:language'"
            )
        name, value, language = name.strip(), value.strip(), language.strip()
        if not name or not value or not language:
            raise ValueError(
                f"Invalid {field_name} entry {entry!r}; expected 'name:value' or 'name:value:language'"
            )
        parsed[name] = Recipient(value=value, language=language)
    return parsed


def _parse_api_keys(raw, field_name="PUSHBULLET_API_KEYS"):
    """Parse a comma-separated 'name:value' string into an ordered {name: value} dict.

    Backward-compatible view over _parse_recipients() that drops the
    per-recipient language, for callers that send identical content to
    everyone regardless of language.
    """
    return {name: recipient.value for name, recipient in _parse_recipients(raw, field_name).items()}


def get_requested_languages():
    """Return the set of languages actually requested by configured recipients.

    Falls back to {TRANSLATION_LANGUAGE} when no recipients are configured, so
    content generation never runs for a language nobody asked for.
    """
    cfg = get_config()
    pb_recipients = _parse_recipients(cfg.PUSHBULLET_API_KEYS)
    email_recipients = _parse_recipients(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")
    languages = {r.language for r in pb_recipients.values()} | {r.language for r in email_recipients.values()}
    return languages or {cfg.TRANSLATION_LANGUAGE}


def _send_pushbullet(title, body, api_keys):
    logger.info(f"Sending Pushbullet notification with title: {title}")
    logger.debug(f"Notification body:\n{body}")
    params = {"type": "note", "title": title, "body": body}
    for name, key in api_keys.items():
        logger.debug(f"Pushing notification to recipient '{name}'")
        response = requests.post(
            "https://api.pushbullet.com/v2/pushes",
            data=json.dumps(params),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
    logger.info("Pushbullet notification sent")


def _send_email(title, body, sender, app_password, recipients):
    """Send the notification by email via Gmail SMTP, one message per recipient.

    Each recipient is emailed separately so their address is never exposed to
    the others. Raises if sender/app password are missing or SMTP fails, so a
    failed send leaves the article unmarked for retry on the next run.
    """
    if not sender or not app_password:
        raise ValueError(
            "EMAIL_RECIPIENTS is set but EMAIL_SENDER and/or EMAIL_APP_PASSWORD are empty"
        )
    logger.info(f"Sending email notification with title: {title}")
    logger.debug(f"Notification body:\n{body}")
    with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
        server.login(sender, app_password)
        for name, address in recipients.items():
            logger.debug(f"Emailing notification to recipient '{name}' <{address}>")
            message = EmailMessage()
            message["Subject"] = title
            message["From"] = sender
            message["To"] = address
            message.set_content(body)
            server.send_message(message)
    logger.info("Email notification sent")


def send_notification(title, body, api_keys=None):
    cfg = get_config()
    if api_keys is None:
        api_keys = _parse_api_keys(cfg.PUSHBULLET_API_KEYS)
    elif isinstance(api_keys, str):
        api_keys = _parse_api_keys(api_keys)

    email_recipients = _parse_api_keys(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")

    if not api_keys and not email_recipients:
        logger.warning(
            "No notification channels configured; set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS"
        )
        notify_admin(
            "No notification channels configured",
            "Set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS; nobody is being notified.",
        )
        return

    if api_keys:
        _send_pushbullet(title, body, api_keys)
    if email_recipients:
        _send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD, email_recipients)


def send_multilingual_notification(content_by_language):
    """Send localized content to each recipient in their own configured language.

    content_by_language maps language code -> (title, body). Recipients
    (Pushbullet and email alike) are grouped by their configured language
    (falling back to TRANSLATION_LANGUAGE) and each group only ever receives
    the content for its own language — a language that's missing from
    content_by_language is simply skipped, since nothing was generated for it.
    """
    cfg = get_config()
    pb_recipients = _parse_recipients(cfg.PUSHBULLET_API_KEYS)
    email_recipients = _parse_recipients(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")

    if not pb_recipients and not email_recipients:
        logger.warning(
            "No notification channels configured; set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS"
        )
        notify_admin(
            "No notification channels configured",
            "Set PUSHBULLET_API_KEYS and/or EMAIL_RECIPIENTS; nobody is being notified.",
        )
        return

    languages = {r.language for r in pb_recipients.values()} | {r.language for r in email_recipients.values()}
    for language in languages:
        if language not in content_by_language:
            logger.warning(f"No content generated for language '{language}'; skipping its recipients")
            continue
        title, body = content_by_language[language]
        lang_pb_keys = {name: r.value for name, r in pb_recipients.items() if r.language == language}
        lang_email_recipients = {name: r.value for name, r in email_recipients.items() if r.language == language}
        if lang_pb_keys:
            _send_pushbullet(title, body, lang_pb_keys)
        if lang_email_recipients:
            _send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD, lang_email_recipients)


def _format_admin_alert(summary, detail=None, exc=None):
    sections = [summary]
    if detail:
        sections.append(str(detail))
    if exc is not None:
        sections.append(f"{type(exc).__name__}: {exc}")
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        if trace:
            sections.append(trace)
    return "\n\n".join(sections)


def notify_admin(summary, detail=None, exc=None):
    """Best-effort alert to the admin channel about a problem in this run.

    Never raises: an admin channel that is down must not itself break the run or
    cause an otherwise-successful article to be retried forever.
    """
    try:
        cfg = get_config()
    except Exception as e:
        logger.error(f"Admin alert skipped, config unavailable: {e}")
        return

    if not cfg.ADMIN_PUSHBULLET_API_KEY and not cfg.ADMIN_EMAIL:
        return

    title = f"[Social Schools admin] {summary}"
    body = _format_admin_alert(summary, detail, exc)

    if cfg.ADMIN_PUSHBULLET_API_KEY:
        try:
            _send_pushbullet(title, body, {"admin": cfg.ADMIN_PUSHBULLET_API_KEY})
        except Exception as e:
            logger.error(f"Failed to send admin Pushbullet alert: {e}")
    if cfg.ADMIN_EMAIL:
        try:
            _send_email(title, body, cfg.EMAIL_SENDER, cfg.EMAIL_APP_PASSWORD, {"admin": cfg.ADMIN_EMAIL})
        except Exception as e:
            logger.error(f"Failed to send admin email alert: {e}")


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


# --- LLM provider seam -------------------------------------------------------
# A provider turns a prompt into completion text and nothing else. Per ADR 0002,
# every provider MUST behave as a pure text transformer: no tools, no function
# calling, no URL fetching. Article/attachment text is untrusted input, so the
# worst case of a poisoned message must stay "a low-quality Digest", never code
# execution or a network side effect chosen by the model.
#
# Providers are constructed lazily via get_provider(), which is only ever called
# from the Digest code path. When DIGEST_ENABLED is false no provider is built,
# so Translation mode stays completely free of LLM machinery.


class LLMProvider:
    """Interface for turning a prompt into completion text."""

    def health_check(self) -> None:
        """Fail fast (raise RuntimeError) if the backend is not reachable."""
        raise NotImplementedError

    def complete(self, prompt: str) -> str:
        """Return the model's completion text for the given prompt."""
        raise NotImplementedError


# What the last completion cost, in tokens/money/seconds. A module global rather
# than a return value because get_provider() builds a fresh provider per call;
# only the evaluation harness reads it, and only right after a generation.
_LAST_USAGE = {}


def get_last_llm_usage():
    """Usage of the most recent completion. Empty when the backend reports none."""
    return dict(_LAST_USAGE)


def _record_usage(usage):
    _LAST_USAGE.clear()
    _LAST_USAGE.update(usage)


class CopilotCliProvider(LLMProvider):
    """Default backend: the GitHub Copilot CLI in non-interactive, tool-free mode (ADR 0001/0002)."""

    def health_check(self) -> None:
        _check_copilot_available()

    def complete(self, prompt: str) -> str:
        started = time.monotonic()
        text = _run_copilot(prompt)
        # The CLI bills against a request quota and reports no token counts.
        _record_usage({"latency_s": round(time.monotonic() - started, 2), "requests": 1})
        return text


# A 4xx from a chat endpoint most often means "I don't know this option" rather
# than "your request is malformed", so an unsupported extra can be dropped and retried.
_UNSUPPORTED_OPTION_STATUSES = (400, 404, 422)


def _usage_from_response(data, latency_s):
    """Token counts, and money when the endpoint reports it, for one completion."""
    usage = data.get("usage") or {}
    recorded = {"latency_s": round(latency_s, 2), "requests": 1}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if isinstance(usage.get(key), int):
            recorded[key] = usage[key]
    if isinstance(usage.get("cost"), (int, float)):
        recorded["cost_usd"] = float(usage["cost"])
    return recorded


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible /chat/completions endpoint.

    One adapter covers local/LAN Ollama (http://host:11434/v1), OpenRouter,
    and most cloud providers. No 'tools'/'functions' are ever sent (ADR 0002).
    """

    def __init__(self, base_url, model, api_key="", timeout=120,
                 reasoning_effort="", structured_output=True):
        if not base_url:
            raise RuntimeError("LLM_BASE_URL is required for the 'openai_compatible' provider")
        if not model:
            raise RuntimeError("LLM_MODEL is required for the 'openai_compatible' provider")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self.structured_output = structured_output
        # Only OpenRouter accepts (and answers) the cost-reporting flag; sending
        # it to Ollama or a plain OpenAI endpoint risks a rejected request.
        self.reports_cost = "openrouter.ai" in self.base_url

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health_check(self) -> None:
        try:
            resp = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
        except requests.RequestException as e:
            raise RuntimeError(f"LLM endpoint unreachable at {self.base_url}: {e}")
        # Local/key-less servers may reject /models with 4xx; only a 5xx means the
        # endpoint itself is unhealthy. Anything reachable is good enough to proceed.
        if resp.status_code >= 500:
            raise RuntimeError(
                f"LLM endpoint health check failed ({resp.status_code}) at {self.base_url}"
            )

    def _post(self, payload):
        try:
            return requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"LLM request to {self.base_url} failed: {e}")

    def complete(self, prompt: str) -> str:
        # ADR 0002: deliberately no 'tools'/'functions' key — pure text transformer only.
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Structured extraction, not creative writing: sample deterministically.
            "temperature": 0,
        }
        if self.structured_output:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": DIGEST_JSON_SCHEMA}
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.reports_cost:
            payload["usage"] = {"include": True}

        started = time.monotonic()
        resp = self._post(payload)
        if resp.status_code in _UNSUPPORTED_OPTION_STATUSES and "response_format" in payload:
            # Not every model behind an OpenAI-compatible endpoint implements
            # json_schema. Degrade to prompt-only JSON for the rest of this run.
            logger.warning(
                f"{self.model} rejected structured output ({resp.status_code}); "
                "retrying without a response schema")
            self.structured_output = False
            payload.pop("response_format")
            resp = self._post(payload)
        if resp.status_code != 200:
            logger.error(f"LLM endpoint error body:\n{resp.text}")
            raise RuntimeError(f"LLM endpoint returned status {resp.status_code}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise RuntimeError(f"Unexpected LLM response shape: {e}")
        _record_usage(_usage_from_response(data, time.monotonic() - started))
        return content


def get_provider() -> LLMProvider:
    """Build the configured LLM provider. Lazy — called only from the Digest path."""
    cfg = get_config()
    provider = (cfg.LLM_PROVIDER or "copilot").strip().lower()
    if provider == "copilot":
        return CopilotCliProvider()
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=cfg.LLM_BASE_URL,
            model=cfg.LLM_MODEL,
            api_key=cfg.LLM_API_KEY,
            timeout=cfg.LLM_TIMEOUT,
            reasoning_effort=cfg.LLM_REASONING_EFFORT,
            structured_output=cfg.LLM_STRUCTURED_OUTPUT,
        )
    raise RuntimeError(
        f"Unknown LLM_PROVIDER {provider!r}; expected 'copilot' or 'openai_compatible'"
    )


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


def _clean_entry_list(value, where):
    """Validate a topic's entry list and drop duplicates, preserving order."""
    if not isinstance(value, list):
        raise ValueError(f"'{where}' must be a list")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"'{where}' must contain only non-empty strings")
    return list(dict.fromkeys(value))


def _dict_to_digest(data: dict) -> Digest:
    """Validate a raw JSON dict's semantics (not just its shape) and convert it to a typed Digest.

    Raises ValueError on missing/malformed fields, non-string list items, or a digest that carries
    no actual content, so callers can retry instead of silently accepting an incomplete brief.
    """
    missing = REQUIRED_DIGEST_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    if not isinstance(data.get("translated_title"), str) or not data["translated_title"].strip():
        raise ValueError("'translated_title' must be a non-empty string")
    if not isinstance(data.get("tldr"), str):
        raise ValueError("'tldr' must be a string")
    if not isinstance(data.get("topics"), list):
        raise ValueError("'topics' must be a list")

    topics = []
    for raw in data["topics"]:
        if not isinstance(raw, dict):
            raise ValueError("Each topic must be an object")
        heading = raw.get("heading", "")
        if not isinstance(heading, str):
            raise ValueError("'heading' must be a string")
        topic = Topic(
            heading=heading.strip(),
            actions=_clean_entry_list(raw.get("actions", []), "actions"),
            bring=_clean_entry_list(raw.get("bring", []), "bring"),
            notes=_clean_entry_list(raw.get("notes", []), "notes"),
        )
        if topic.actions or topic.bring or topic.notes:
            topics.append(topic)

    if not data["tldr"].strip() and not topics:
        raise ValueError("Digest has no content: 'tldr' is empty and no topic carries any entry")

    return Digest(
        translated_title=data["translated_title"],
        tldr=data["tldr"],
        topics=topics,
    )


def _extract_action_hints(text):
    """Pull candidate dates, times, and imperative phrases out of raw text as hints for the Digest prompt.

    This is a lightweight heuristic pre-pass, not a substitute for the model's judgment: it just
    surfaces likely obligations/dates in the source text so the prompt can point the model at them
    instead of relying purely on it to notice them unaided.
    """
    hints = []
    for match in _DATE_HINT_RE.finditer(text):
        hints.append(f"date: {match.group(0).strip()}")
    for match in _TIME_HINT_RE.finditer(text):
        hints.append(f"time: {match.group(0)}")
    for match in _IMPERATIVE_HINT_RE.finditer(text):
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 40)
        snippet = " ".join(text[start:end].split())
        hints.append(f"instruction: \u2026{snippet}\u2026")
    return hints


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


def _resolve_relative_dutch_date(text, today):
    """Resolve 'vandaag' / 'gisteren' / '(afgelopen) dinsdag' to a concrete date, or None."""
    relative = _RELATIVE_DAY_RE.search(text)
    if relative:
        return today - timedelta(days=_RELATIVE_DAY_OFFSETS[relative.group(1).lower()])

    weekday = _WEEKDAY_RE.search(text)
    if weekday:
        # Social Schools only labels days this way when they are in the recent past.
        days_back = (today.weekday() - _DUTCH_WEEKDAYS[weekday.group(1).lower()]) % 7 or 7
        return today - timedelta(days=days_back)

    return None


def _get_post_date(article, today=None):
    """Return the post's date/time as 'D Mon' or 'D Mon HH:MM', or None if unavailable.

    Social Schools does not render a machine-readable <time datetime=...> element; the post
    date/time is plain Dutch text inside a link. Older posts carry a month name ('7 juli om 13:19')
    while recent ones are relative ('vandaag om 15:47', 'afgelopen dinsdag om 15:39'), so both forms
    are handled here. Only the leading segment is read, since an edited post appends a second
    ', bijgewerkt ...' timestamp that would otherwise mask the original posting time.
    """
    date_el = article.query_selector("a.meta-info")
    if not date_el:
        return None
    raw = date_el.inner_text()
    if not raw:
        return None
    posted = raw.split(",")[0]

    match = _POST_DATETIME_RE.search(posted)
    if match:
        day, month_nl, time_part = match.group(1), match.group(2).lower(), match.group(3)
        month_abbr = _DUTCH_MONTHS.get(month_nl)
        if not month_abbr:
            return None
        result = f"{int(day)} {month_abbr}"
        if time_part:
            result += f" {time_part}"
        return result

    resolved = _resolve_relative_dutch_date(posted, today or date.today())
    if not resolved:
        return None
    result = f"{resolved.day} {_MONTH_ABBR[resolved.month - 1]}"
    time_match = _TIME_OF_DAY_RE.search(posted)
    if time_match:
        result += f" {time_match.group(1)}"
    return result


def render_digest_notification(data: Digest, failed_attachments=None, original_title=None, post_date=None):
    sections = []

    if post_date:
        sections.append(f"\U0001F4C5 {post_date}")

    tldr = data.tldr.strip()
    if tldr:
        sections.append(tldr)

    for topic in data.topics:
        lines = []
        if topic.heading:
            lines.append(f"\u2501 {topic.heading}")
        lines.extend(f"\u25b8 {action}" for action in topic.actions)
        if topic.bring:
            lines.append("\U0001F392 Bring: " + ", ".join(topic.bring))
        lines.extend(f"\u00b7 {note}" for note in topic.notes)
        sections.append("\n".join(lines))

    if not any(topic.actions or topic.bring for topic in data.topics):
        sections.append("No action needed")

    if failed_attachments:
        sections.append("\u26a0 An attachment could not be read \u2014 check the original post for complete info")

    if original_title:
        sections.append(f"To find this post in Social Schools, look for: \"{original_title}\"")

    return "\n\n".join(sections)


def generate_digest(title, body, attachments, language=None):
    if language is None:
        language = get_config().TRANSLATION_LANGUAGE
    attachment_text = ""
    if attachments:
        parts = [f"\n\n[Attachment: {a.filename}]\n{a.text}" for a in attachments if not a.failed]
        failed_parts = [f"\n\n[Attachment: {a.filename} \u2014 could not be extracted]" for a in attachments if a.failed]
        attachment_text = "".join(parts + failed_parts)

    hint_source = "\n".join([body] + [a.text for a in attachments if not a.failed])
    hints = _extract_action_hints(hint_source)
    hints_text = ""
    if hints:
        hints_text = (
            "\n\nPre-scan hints (candidate dates/times/instructions detected automatically; "
            "verify each against the message above \u2014 don't invent an item just because it's "
            "listed here):\n" + "\n".join(f"- {h}" for h in hints)
        )

    prompt = DIGEST_PROMPT_TEMPLATE.format(
        language=language,
        title=title,
        body=body,
        attachments=attachment_text,
        hints=hints_text,
    )

    provider = get_provider()
    logger.info(f"Generating Digest via {type(provider).__name__}")
    raw = provider.complete(prompt)
    logger.debug(f"LLM raw response:\n{raw}")

    try:
        digest = _dict_to_digest(_extract_json(raw))
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Digest response invalid ({e}), retrying once")
        retry_prompt = (
            "The previous response was not valid JSON, was missing required fields, or had no "
            f"actual content. Respond with ONLY this JSON structure (no markdown, no explanation), "
            f"with every text value written in {language}:\n"
            '{\n  "translated_title": "...",\n  "tldr": "...",\n'
            '  "topics": [{"heading": "...", "actions": [...], "bring": [...], "notes": [...]}]\n}\n\n'
            f"Previous invalid response:\n{raw}\n\n"
            f"Original prompt:\n{prompt}"
        )
        raw = provider.complete(retry_prompt)
        try:
            digest = _dict_to_digest(_extract_json(raw))
        except (ValueError, json.JSONDecodeError) as e2:
            logger.warning(f"Digest retry also invalid ({e2}), using safe fallback")
            notify_admin(
                "Digest degraded to fallback text",
                f"Article: {title}\nThe LLM returned an invalid digest twice; parents got a placeholder summary.",
                exc=e2,
            )
            digest = Digest(
                translated_title=title,
                tldr="(Could not generate summary \u2014 open the original post for details)",
                topics=[],
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
                notify_admin("Attachment could not be processed", f"PDF: {pdf_filename}\nURL: {pdf_url}", exc=e)
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
                notify_admin("Attachment could not be processed", f"DOCX: {docx_filename}\nURL: {docx_url}", exc=e)
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
                get_provider().health_check()
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
        # The application redirects to a separate authentication host after its
        # initial shell loads. Waiting for network idle can finish before that
        # asynchronous redirect on slower devices, such as a Raspberry Pi.
        page.goto("https://app.socialschools.eu/home", wait_until="domcontentloaded")

        username_field = page.locator("#username")
        try:
            username_field.wait_for(state="visible", timeout=60000)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Username field not found after waiting for the login page (URL: {page.url})"
            ) from error
        username_field.fill(get_config().SCRAPED_WEBSITE_USER)

        password_field = page.locator("#Password")
        try:
            password_field.wait_for(state="visible", timeout=60000)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Password field not found after waiting for the login page (URL: {page.url})"
            ) from error
        password_field.fill(get_config().SCRAPED_WEBSITE_PASSWORD)

        password_field.press("Enter")

        try:
            page.wait_for_url(
                "https://app.socialschools.eu/home**",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Login did not return to the Social Schools home page (URL: {page.url})"
            ) from error
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def process_all_articles(playwright, browser, context, page):
    try:
        logger.debug("Looking for feed element")
        try:
            page.locator("div[role='feed']").wait_for(state="visible", timeout=60000)
        except PlaywrightTimeoutError as error:
            raise Exception(
                f"Feed element did not load on the Social Schools home page (URL: {page.url})"
            ) from error
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
                succeeded = process_article_content(playwright, browser, context, article)
                if not succeeded:
                    # Left unmarked deliberately so the next run retries it.
                    logger.warning(f"Article {article_id} not fully processed, leaving unmarked")
                    continue
                if not FORCE_REPROCESS:
                    save_processed_article(article_id)
                    processed_ids.append(article_id)
            except Exception as e:
                logger.error(f"Error processing article {article_id}: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                notify_admin(
                    "Article processing failed",
                    f"Article: {title} [{article_id}]\nLeft unmarked; it will be retried on the next run.",
                    exc=e,
                )
                # Continue to next article; leave unmarked for retry

    except Exception as e:
        logger.error(f"Error in process_all_articles: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def expand_full_text(article):
    """Expand article text if the UI offers a 'Meer weergeven' control.

    Some articles may not render the expected full-text container at all, or the
    content may already be in the visible DOM without the legacy selector. In
    those cases we should log and continue rather than aborting the entire run.
    """
    try:
        more_button = article.query_selector("button:has-text('Meer weergeven')")
        if more_button:
            logger.info("Clicking 'Meer weergeven' to expand article text")
            try:
                more_button.click()
            except Exception as e:
                logger.warning(f"Could not click 'Meer weergeven': {e}")

        try:
            article.wait_for_selector("span[as='div']", timeout=10000)
            return
        except Exception:
            logger.warning(
                "Legacy full-text selector not found within timeout; trying a more tolerant fallback "
                "before giving up."
            )

        try:
            article.wait_for_selector(
                "[data-testid='article-body'], [data-test='article-body'], div[role='article'] span, p",
                timeout=10000,
            )
            return
        except Exception as fallback_error:
            logger.warning(
                "Full-text content could not be located with the legacy or fallback selectors: "
                f"{fallback_error}"
            )
            return
    except Exception as e:
        logger.error(f"Error expanding full text: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        # Some articles may legitimately not expose a full-text container. Do not
        # crash the whole run; processors can still inspect the visible body and fail
        # gracefully per article.
        return


def _read_visible_article_body(article):
    """Return the first readable body element or raise a helpful ValueError."""
    selectors = [
        "span[as='div']",
        "[data-testid='article-body']",
        "[data-test='article-body']",
        "div[role='article'] span",
        "p",
        "div",
    ]

    for selector in selectors:
        element = article.query_selector(selector)
        if not element:
            continue
        try:
            text = element.inner_text()
            if text and text.strip():
                return text
        except Exception as exc:
            logger.debug(f"Selector {selector!r} did not yield text: {exc}")

    raise ValueError("No readable article body found in the visible DOM")


def process_article_content(playwright, browser, context, article):
    """Process one article end to end.

    Returns True only when the article was fully handled and every notification
    was delivered, so the caller may mark it processed. Returns False (or raises)
    otherwise, leaving the article unmarked for retry on the next run.
    """
    try:
        body = _read_visible_article_body(article)
    except ValueError as exc:
        logger.warning(f"Skipping article with no readable body: {exc}")
        notify_admin(
            "Article body could not be read",
            "The article markup did not match any known body selector; it stays unmarked for retry.",
            exc=exc,
        )
        return False

    title_el = article.query_selector("h3")
    title = title_el.inner_text() if title_el else "(no title)"

    if not get_config().DIGEST_ENABLED:
        # Translation-only mode: no LLM, no attachment extraction. Each
        # requested language is translated exactly once and shared by every
        # recipient who wants that language.
        logger.info("Digest disabled — sending translated content directly")
        content = {
            language: (translate(title, dest=language), translate(body, dest=language))
            for language in get_requested_languages()
        }
        send_multilingual_notification(content)
        return True

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

    # Generate one Digest per requested language — never more than the
    # languages recipients actually asked for.
    languages = get_requested_languages()
    try:
        digests = {language: generate_digest(title, body, attachments, language=language) for language in languages}
    except RuntimeError as e:
        logger.error(f"Digest generation failed: {e}")
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
                post_date=_get_post_date(article),
            ),
        )
        for language, digest in digests.items()
    }
    send_multilingual_notification(content)
    return True


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
        notify_admin("Run aborted with a fatal error", "No further articles were processed.", exc=e)
        raise
