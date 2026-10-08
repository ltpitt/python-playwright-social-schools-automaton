"""Choosing the one line of encouragement a parent sees at the bottom of a Digest.

The quotes are the user's own local CSV (`var/quotes.csv`), drawn from a shuffled deck
so every quote is used once before any is used again. A model asked for a fresh
sentence each time returns the same one at temperature 0, which is how this came
to exist. A missing CSV means no quote and an unchanged notification.
"""
import csv
import hashlib
import json
import logging
import random

from . import paths
from .models import Quote
from .translate import translate

logger = logging.getLogger(__name__)

# Only humorous and playful quotes get one; a serious line with an emoji reads as flippant.
LIGHT_TONES = ("humorous", "playful")
LIGHT_TONE_EMOJI = ("\U0001F604", "\U0001F605", "\U0001F643", "\U0001F609", "\U0001F60F", "\U0001F92D")


def _default_emoji(quote_id, tone):
    if tone not in LIGHT_TONES:
        return ""
    digest = hashlib.sha256(quote_id.encode("utf-8")).hexdigest()
    return LIGHT_TONE_EMOJI[int(digest, 16) % len(LIGHT_TONE_EMOJI)]


def load_quotes(path=None):
    """Every usable quote in the CSV, or none when the file is absent."""
    path = path or paths.QUOTES_FILE
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return []

    quotes = {}
    for row in rows:
        quote_id = (row.get("id") or "").strip()
        text = (row.get("quote") or "").strip()
        if not quote_id or not text or quote_id in quotes:
            continue
        tone = (row.get("tone") or "").strip().lower()
        emoji = (row.get("emoji") or "").strip() or _default_emoji(quote_id, tone)
        quotes[quote_id] = Quote(id=quote_id, text=text,
                                 language=(row.get("language") or "en").strip().lower() or "en",
                                 tone=tone, emoji=emoji)
    return list(quotes.values())


def _load_deck(path):
    """(remaining, used) quote ids, or empty lists when the state is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        remaining, used = state["remaining"], state["used"]
        if all(isinstance(i, str) for i in remaining + used):
            return remaining, used
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return [], []


def _save_deck(path, remaining, used):
    try:
        with open(paths.ensure_parent(path), "w", encoding="utf-8") as f:
            json.dump({"remaining": remaining, "used": used}, f)
    except OSError as e:
        logger.warning(f"Could not save the quote rotation ({e}); the next quote may repeat")


def _new_deck(ids, previous, rng):
    """A shuffled deck whose first picks are never from the last half of the previous one."""
    half = len(ids) // 2
    recent = previous[-half:] if half else []
    fresh = [i for i in ids if i not in recent]
    recent = [i for i in ids if i in recent]
    rng.shuffle(fresh)
    rng.shuffle(recent)
    return fresh + recent


def draw_quote(quotes=None, state_path=None, rng=random):
    """The next quote in the rotation, or None when there are no quotes."""
    quotes = load_quotes() if quotes is None else quotes
    if not quotes:
        return None
    by_id = {q.id: q for q in quotes}
    state_path = state_path or paths.QUOTE_DECK_FILE

    remaining, used = _load_deck(state_path)
    remaining = [i for i in remaining if i in by_id]
    used = [i for i in used if i in by_id]
    for new_id in by_id:
        if new_id not in remaining and new_id not in used:
            remaining.insert(rng.randint(0, len(remaining)), new_id)
    if not remaining:
        remaining, used = _new_deck(list(by_id), used, rng), []

    chosen = remaining.pop(0)
    used.append(chosen)
    _save_deck(state_path, remaining, used)
    return by_id[chosen]


def quote_line(quote, language):
    """The quote as the reader sees it: in their language, with its emoji when it has one."""
    text = quote.text
    if quote.language != language:
        try:
            text = translate(text, src=quote.language, dest=language)
        except Exception as e:
            logger.warning(f"Could not translate quote {quote.id} to {language} ({e}); sending it as written")
    return f"{text} {quote.emoji}" if quote.emoji else text
