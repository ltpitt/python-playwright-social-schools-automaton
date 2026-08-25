"""One Article in, one validated Digest out.

An invalid answer gets exactly one retry, shown what was wrong. A second
failure produces a placeholder brief that tells the parent to open the original
post, and raises an admin alert — a notification that admits it is empty is
better than no notification and better than an infinite retry loop.
"""
import json
import logging

from ..config import get_config
from ..delivery.admin import notify_admin
from ..llm.provider import get_provider
from ..models import Digest
from .hints import extract_action_hints
from .parse import dict_to_digest, extract_json
from .prompt import DIGEST_PROMPT_TEMPLATE, render_prompt

logger = logging.getLogger(__name__)

FALLBACK_TLDR = "(Could not generate summary \u2014 open the original post for details)"


def _attachment_section(attachments):
    if not attachments:
        return ""
    extracted = [f"\n\n[Attachment: {a.filename}]\n{a.text}" for a in attachments if not a.failed]
    failed = [f"\n\n[Attachment: {a.filename} \u2014 could not be extracted]"
              for a in attachments if a.failed]
    return "".join(extracted + failed)


def _hints_section(body, attachments):
    source = "\n".join([body] + [a.text for a in attachments if not a.failed])
    hints = extract_action_hints(source)
    if not hints:
        return ""
    return (
        "\n\nPre-scan hints (candidate dates/times/instructions detected automatically; "
        "verify each against the message above \u2014 don't invent an item just because it's "
        "listed here):\n" + "\n".join(f"- {h}" for h in hints)
    )


def _retry_prompt(language, raw, prompt):
    return (
        "The previous response was not valid JSON, was missing required fields, or had no "
        "actual content. Respond with ONLY this JSON structure (no markdown, no explanation), "
        f"with every text value written in {language}:\n"
        '{\n  "translated_title": "...",\n  "tldr": "...",\n'
        '  "topics": [{"heading": "...", "actions": [...], "bring": [...], "notes": [...]}]\n}\n\n'
        f"Previous invalid response:\n{raw}\n\n"
        f"Original prompt:\n{prompt}"
    )


def generate_digest(title, body, attachments, language=None):
    if language is None:
        language = get_config().TRANSLATION_LANGUAGE

    prompt = render_prompt(
        DIGEST_PROMPT_TEMPLATE,
        language=language,
        title=title,
        body=body,
        attachments=_attachment_section(attachments),
        hints=_hints_section(body, attachments),
    )

    provider = get_provider()
    logger.info(f"Generating Digest via {type(provider).__name__}")
    raw = provider.complete(prompt)
    logger.debug(f"LLM raw response:\n{raw}")

    try:
        digest = dict_to_digest(extract_json(raw))
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Digest response invalid ({e}), retrying once")
        raw = provider.complete(_retry_prompt(language, raw, prompt))
        try:
            digest = dict_to_digest(extract_json(raw))
        except (ValueError, json.JSONDecodeError) as e2:
            logger.warning(f"Digest retry also invalid ({e2}), using safe fallback")
            notify_admin(
                "Digest degraded to fallback text",
                f"Article: {title}\nThe LLM returned an invalid digest twice; "
                "parents got a placeholder summary.",
                exc=e2,
            )
            return Digest(translated_title=title, tldr=FALLBACK_TLDR, topics=[])

    logger.info("Digest validated successfully")
    return digest
