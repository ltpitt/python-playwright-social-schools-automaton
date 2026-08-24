"""Loads the instruction given to the model when turning an Article into a Digest.

The template lives in `digest_prompt.txt` rather than in this file because
`goal.py` rewrites it unattended, and the text it rewrites toward is shaped by
Article content the school website supplies. Data cannot execute; a Python
module rewritten from untrusted input would, on the next import. Keeping the
template inert is what preserves ADR 0002's promise that the worst case of a
poisoned attachment is a poor Digest (ADR 0006).

Placeholders are filled by generate_digest(): language, title, body,
attachments, hints. Literal braces in the JSON example are doubled.
"""
import os

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digest_prompt.txt")

# Placeholders generate_digest() supplies; a template missing one cannot render.
PROMPT_PLACEHOLDERS = ("language", "title", "body", "attachments", "hints")


def load_prompt_template(path=PROMPT_PATH):
    """The Digest prompt template as str.format() expects it."""
    with open(path, encoding="utf-8") as f:
        # The file ends with a newline because text files do; the prompt does not.
        return f.read().rstrip("\n")


DIGEST_PROMPT_TEMPLATE = load_prompt_template()
