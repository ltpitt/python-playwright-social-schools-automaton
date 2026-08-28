"""Who gets notified, and in which language.

One parser for both PUSHBULLET_API_KEYS and EMAIL_RECIPIENTS, because they are
the same shape: 'name:value[:language]'. A malformed entry raises rather than
being skipped, so a typo means a loud failure instead of a person who quietly
stops receiving anything.
"""
from ..config import get_config
from ..models import Recipient


def parse_recipients(raw, field_name="PUSHBULLET_API_KEYS", default_language=None):
    """Parse a comma-separated 'name:value[:language]' string into {name: Recipient}.

    The trailing ':language' is optional and defaults to TRANSLATION_LANGUAGE,
    so existing 'name:value' entries keep working unchanged.
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


def parse_api_keys(raw, field_name="PUSHBULLET_API_KEYS"):
    """The same list as {name: value}, for callers that send everyone the same thing."""
    return {name: recipient.value for name, recipient in parse_recipients(raw, field_name).items()}


def get_requested_languages():
    """The languages configured recipients actually asked for.

    Falls back to {TRANSLATION_LANGUAGE} when nobody is configured, so content
    generation never runs for a language nobody wants.
    """
    cfg = get_config()
    pushbullet = parse_recipients(cfg.PUSHBULLET_API_KEYS)
    email = parse_recipients(cfg.EMAIL_RECIPIENTS, field_name="EMAIL_RECIPIENTS")
    languages = {r.language for r in pushbullet.values()} | {r.language for r in email.values()}
    return languages or {cfg.TRANSLATION_LANGUAGE}
