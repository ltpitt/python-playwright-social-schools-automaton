"""Snapshot real Social Schools posts into a local evaluation corpus.

The corpus is what `evaluate_digests.py` runs against, so it must be real
content: invented posts would only prove the digest handles invented posts.

The OUTPUT of this script is personal data (real posts name children, teachers
and classes) and is gitignored. This script itself is not — it only contains
code. Never commit anything it writes. See the personal-data rules in
.github/copilot-instructions.md.

No notifications are sent and production processed-article state is untouched.
"""
import argparse
import json
import logging
import os

from playwright.sync_api import sync_playwright

from get_social_schools_news import (
    _get_article_id,
    _get_post_date,
    _read_visible_article_body,
    expand_full_text,
    login_to_website,
    process_docx_links,
    process_pdf_links,
    resolve_browser_executable_path,
)

logger = logging.getLogger(__name__)

DEFAULT_OUT = "corpus/corpus.json"
DEFAULT_PROCESSED = "processed_corpus_articles.json"


def collect_article(playwright, browser, context, article, with_attachments):
    """Snapshot one article exactly as the digest pipeline would see it."""
    expand_full_text(article)

    title_el = article.query_selector("h3")
    try:
        body = _read_visible_article_body(article)
    except ValueError as exc:
        logger.warning(f"Skipping article with no readable body: {exc}")
        return None

    attachments = []
    if with_attachments:
        pdf_links = article.query_selector_all("a[href*='.pdf']")
        if pdf_links:
            attachments.extend(process_pdf_links(playwright, browser, context, pdf_links))
        docx_links = article.query_selector_all("a[href*='.docx']")
        if docx_links:
            attachments.extend(process_docx_links(playwright, browser, context, docx_links))

    return {
        "id": _get_article_id(article),
        "title": title_el.inner_text() if title_el else "(no title)",
        "post_date": _get_post_date(article),
        "body": body,
        "attachments": [
            {
                "filename": a.filename,
                "filetype": a.filetype,
                "failed": a.failed,
                # URLs are session-scoped and re-identifying, so only text is kept.
                "text": a.text,
            }
            for a in attachments
        ],
    }


def build_corpus(limit, with_attachments, processed_ids=None):
    cases = []
    processed_ids = set(processed_ids or [])
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        executable_path = resolve_browser_executable_path()
        if executable_path:
            launch_options["executable_path"] = executable_path

        browser = playwright.chromium.launch(**launch_options)
        try:
            context = browser.new_context()
            page = context.new_page()
            login_to_website(page)
            if "home" not in page.url:
                raise RuntimeError(f"Login failed - unexpected URL: {page.url}")

            page.locator("div[role='feed']").wait_for(state="visible", timeout=60000)
            feed = page.query_selector("div[role='feed']")
            if not feed:
                raise RuntimeError("Feed element not found")

            articles = feed.query_selector_all("div[role='article']")
            candidates = articles if limit <= 0 else articles[:limit]
            for article in candidates:
                article_id = _get_article_id(article)
                if article_id in processed_ids:
                    continue
                case = collect_article(playwright, browser, context, article, with_attachments)
                if case:
                    cases.append(case)
        finally:
            browser.close()
    return cases


def update_corpus(out, processed_path, limit, with_attachments):
    existing = []
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            existing = json.load(f)

    processed_ids = set()
    if os.path.exists(processed_path):
        with open(processed_path, encoding="utf-8") as f:
            processed_ids.update(json.load(f))
    processed_ids.update(case["id"] for case in existing)

    new_cases = build_corpus(limit, with_attachments, set(processed_ids))
    cases = existing + new_cases
    processed_ids.update(case["id"] for case in new_cases)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    with open(processed_path, "w", encoding="utf-8") as f:
        json.dump(sorted(processed_ids), f, indent=2)
    return cases, new_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"output path (default: {DEFAULT_OUT})")
    parser.add_argument("--processed", default=DEFAULT_PROCESSED,
                        help=f"processed ID state (default: {DEFAULT_PROCESSED})")
    parser.add_argument("--limit", type=int, default=0,
                        help="how many feed articles to snapshot; 0 means all")
    parser.add_argument("--no-attachments", action="store_true",
                        help="skip downloading PDFs/Word docs (much faster)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    cases, new_cases = update_corpus(
        args.out, args.processed, args.limit, not args.no_attachments
    )

    print(f"\nCorpus contains {len(cases)} case(s); added {len(new_cases)} new case(s)")
    for case in new_cases:
        attachments = len(case["attachments"])
        print(f"  {case['id']}  {len(case['body']):>5} chars, {attachments} attachment(s)")
    print("\nThis file contains real school posts: personal data. Never commit it.")


if __name__ == "__main__":
    main()
