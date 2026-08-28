"""Google Translate, for Translation mode and for nothing else.

Cached per (text, source, target) because the same title and body are asked for
once per requested language, and a run with two recipients in one language
should pay for one translation.
"""
import logging

from deep_translator import GoogleTranslator

from .config import get_config

logger = logging.getLogger(__name__)

# Google's endpoint rejects very long inputs, so text is split first.
CHUNK_SIZE = 4900

_cache = {}


def translate(text, src="nl", dest=None, chunk_size=CHUNK_SIZE):
    if dest is None:
        dest = get_config().TRANSLATION_LANGUAGE
    cache_key = (text, src, dest)
    if cache_key in _cache:
        logger.debug(f"Translation cache hit ({src} -> {dest}); reusing previous result")
        return _cache[cache_key]
    logger.info(f"Translating text from {src} to {dest}")
    translator = GoogleTranslator(source=src, target=dest)
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    result = " ".join(translator.translate(chunk) for chunk in chunks)
    logger.info("Translation complete")
    _cache[cache_key] = result
    return result
