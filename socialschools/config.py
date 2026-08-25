"""Reading `var/config.ini` into a typed Config, once per process.

Falls back to the committed `config.example.ini` when no config.ini exists, so a
fresh checkout imports and its tests run without anyone having to invent
credentials. The fallback fails honestly at login rather than silently.
"""
import configparser
import os
from dataclasses import dataclass

from . import paths


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


def config_path():
    """The user's config if they have written one, otherwise the committed example."""
    return paths.CONFIG_FILE if os.path.exists(paths.CONFIG_FILE) else paths.EXAMPLE_CONFIG_FILE


def load_config() -> Config:
    parser = configparser.ConfigParser()
    parser.read(config_path())
    section = parser['DEFAULT']

    return Config(
        SCRAPED_WEBSITE_USER=section['SCRAPED_WEBSITE_USER'],
        SCRAPED_WEBSITE_PASSWORD=section['SCRAPED_WEBSITE_PASSWORD'],
        PUSHBULLET_API_KEYS=section.get('PUSHBULLET_API_KEYS', '').strip(),
        EMAIL_SENDER=section.get('EMAIL_SENDER', '').strip(),
        EMAIL_APP_PASSWORD=section.get('EMAIL_APP_PASSWORD', '').strip(),
        EMAIL_RECIPIENTS=section.get('EMAIL_RECIPIENTS', '').strip(),
        ADMIN_PUSHBULLET_API_KEY=section.get('ADMIN_PUSHBULLET_API_KEY', '').strip(),
        ADMIN_EMAIL=section.get('ADMIN_EMAIL', '').strip(),
        TRANSLATION_LANGUAGE=section.get('TRANSLATION_LANGUAGE', 'en'),
        DIGEST_ENABLED=section.get('DIGEST_ENABLED', 'true').strip().lower() == 'true',
        LLM_PROVIDER=section.get('LLM_PROVIDER', 'copilot').strip().lower(),
        LLM_BASE_URL=section.get('LLM_BASE_URL', '').strip(),
        LLM_MODEL=section.get('LLM_MODEL', '').strip(),
        LLM_API_KEY=section.get('LLM_API_KEY', '').strip(),
        LLM_TIMEOUT=int(section.get('LLM_TIMEOUT', '120').strip() or '120'),
        LLM_REASONING_EFFORT=section.get('LLM_REASONING_EFFORT', '').strip().lower(),
        LLM_STRUCTURED_OUTPUT=section.get(
            'LLM_STRUCTURED_OUTPUT', 'true').strip().lower() == 'true',
    )


_config = None


def get_config() -> Config:
    """The process-wide Config, read from disk on first use."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config():
    """Forget the cached Config so the next read picks up a changed file."""
    global _config
    _config = None
