"""Run the real digest flow against a local corpus and save its product.

The output contains personal data and belongs outside git. It is intended for
inspection and evaluation, not notification delivery.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os

from evaluate_digests import structural_violations
from get_social_schools_news import (
    Attachment,
    generate_digest,
    render_digest_notification,
)

DEFAULT_CORPUS = "corpus/corpus.json"
DEFAULT_OUTPUT = "eval_output/product.json"
DEFAULT_PROCESSED = "processed_corpus_articles.json"


def _attachments(case):
    return [
        Attachment(
            filename=item["filename"],
            url="",
            filetype=item["filetype"],
            text=item.get("text", ""),
            failed=item.get("failed", False),
        )
        for item in case.get("attachments", [])
    ]


def _digest_product(digest):
    return asdict(digest)


def run_case(case):
    """Run generation and rendering for one captured source case."""
    attachments = _attachments(case)
    failed = [item.filename for item in attachments if item.failed]
    try:
        digest = generate_digest(
            case["title"], case["body"], attachments
        )
        rendered = render_digest_notification(
            digest,
            failed_attachments=failed,
            original_title=case["title"],
            post_date=case.get("post_date"),
        )
        return {
            "id": case["id"],
            "source": case,
            "product": {
                "digest": _digest_product(digest),
                "notification": rendered,
            },
            "violations": structural_violations(digest, case),
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "source": case,
            "product": None,
            "violations": [f"digest failed: {exc}"],
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_corpus(corpus_path, output_path):
    with open(corpus_path, encoding="utf-8") as stream:
        corpus = json.load(stream)

    cases = [run_case(case) for case in corpus]
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus_path,
        "cases": cases,
        "summary": {
            "total": len(cases),
            "successful": sum(case["error"] is None for case in cases),
            "failed": sum(case["error"] is not None for case in cases),
            "violations": sum(bool(case["violations"]) for case in cases),
        },
    }
    parent = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    return result


def ensure_corpus(corpus_path, processed_path=DEFAULT_PROCESSED, limit=0):
    if os.path.exists(corpus_path):
        return False

    from build_corpus import update_corpus

    update_corpus(corpus_path, processed_path, limit, with_attachments=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--processed", default=DEFAULT_PROCESSED)
    parser.add_argument("--limit", type=int, default=0,
                        help="how many feed articles to snapshot; 0 means all")
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    created = ensure_corpus(args.corpus, args.processed, args.limit)
    if created:
        print(f"Corpus was missing; created it at {args.corpus}")

    result = run_corpus(args.corpus, args.out)
    summary = result["summary"]
    print(
        f"Wrote {summary['total']} product case(s) to {args.out}; "
        f"{summary['violations']} case(s) have violations."
    )
    print("This file contains real school posts: personal data. Never commit it.")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
