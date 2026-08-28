"""Loads and fills the instruction given to the model when turning an Article into a Digest.

The template lives in `prompt.txt` rather than in this file because `goal.py`
rewrites it unattended, and the text it rewrites toward is shaped by Article
content the school website supplies. Data cannot execute; a Python module
rewritten from untrusted input would, on the next import. Keeping the template
inert is what preserves ADR 0002's promise that the worst case of a poisoned
attachment is a poor Digest (ADR 0006).

Placeholders are `<<NAME>>` rather than str.format's braces because the template
is mostly a JSON example. Braces would have to be doubled to survive .format(),
and asking a model to rewrite a JSON document with deliberately wrong-looking
braces is a fight it loses — observed, on the first real goal run.
"""
import os
import re

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")

# Values generate_digest() supplies; a template missing one cannot be filled.
PROMPT_PLACEHOLDERS = ("LANGUAGE", "TITLE", "BODY", "ATTACHMENTS", "HINTS")

_PLACEHOLDER_RE = re.compile(r'<<([A-Z_]+)>>')


def load_prompt_template(path=PROMPT_PATH):
    """The Digest prompt template, placeholders unfilled."""
    with open(path, encoding="utf-8") as f:
        # The file ends with a newline because text files do; the prompt does not.
        return f.read().rstrip("\n")


def render_prompt(template, **values):
    """Fill <<NAME>> placeholders. An unknown one raises rather than reaching the model."""
    filled = template
    for name in PROMPT_PLACEHOLDERS:
        filled = filled.replace(f"<<{name}>>", str(values.get(name.lower(), "")))
    leftover = sorted(set(_PLACEHOLDER_RE.findall(filled)))
    if leftover:
        raise ValueError("unknown placeholder(s): " + ", ".join(f"<<{n}>>" for n in leftover))
    return filled


DIGEST_PROMPT_TEMPLATE = load_prompt_template()
