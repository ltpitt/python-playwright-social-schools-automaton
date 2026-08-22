"""Run the real digest flow against a local corpus and save its product.

The output contains personal data and belongs outside git. It is intended for
inspection and evaluation, not notification delivery.

The LLM variant (model, reasoning effort, structured output) can be overridden
from the command line so the same corpus can be replayed through several models
and compared. The variant is part of every case's fingerprint, so switching
models never silently reuses another model's cached answers.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os

from evaluate_digests import advisory_warnings, structural_violations
from get_social_schools_news import (
    Attachment,
    DIGEST_PROMPT_TEMPLATE,
    generate_digest,
    get_config,
    get_last_llm_usage,
    render_digest_notification,
)

DEFAULT_CORPUS = "corpus/corpus.json"
DEFAULT_OUTPUT = "eval_output/product.json"
DEFAULT_PROCESSED = "processed_corpus_articles.json"
DEFAULT_PRODUCT_STATE = "processed_product_articles.json"
PRODUCT_GENERATOR_VERSION = 3


def apply_llm_overrides(model=None, reasoning=None, structured=None):
    """Point the shared config at one LLM variant for the rest of this process."""
    cfg = get_config()
    if model:
        cfg.LLM_MODEL = model
    if reasoning is not None:
        cfg.LLM_REASONING_EFFORT = reasoning.strip().lower()
    if structured is not None:
        cfg.LLM_STRUCTURED_OUTPUT = structured
    return cfg


def current_variant():
    """The LLM settings a product was generated with, for fingerprints and reports."""
    cfg = get_config()
    return {
        "provider": cfg.LLM_PROVIDER,
        "model": cfg.LLM_MODEL,
        "reasoning_effort": cfg.LLM_REASONING_EFFORT,
        "structured_output": cfg.LLM_STRUCTURED_OUTPUT,
    }


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


def _case_fingerprint(case, samples=1):
    payload = json.dumps(
        {
            "version": PRODUCT_GENERATOR_VERSION,
            "prompt": DIGEST_PROMPT_TEMPLATE,
            "variant": current_variant(),
            "samples": samples,
            "case": case,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _total_usage(usages):
    """Add up what a case cost across its samples: tokens, money, seconds."""
    total = {}
    for usage in usages:
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                total[key] = round(total.get(key, 0) + value, 6)
    return total


def run_case(case, samples=1):
    """Run generation and rendering for one captured source case.

    With samples > 1 the same input is generated repeatedly so the evaluator can
    tell a real quality difference from run-to-run luck. The first sample is the
    product; the rest exist only to measure stability.
    """
    attachments = _attachments(case)
    failed = [item.filename for item in attachments if item.failed]
    digests = []
    usages = []
    try:
        for _ in range(max(1, samples)):
            digests.append(generate_digest(case["title"], case["body"], attachments))
            usages.append(get_last_llm_usage())
        digest = digests[0]
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
            "samples": [_digest_product(item) for item in digests],
            "usage": _total_usage(usages),
            "violations": structural_violations(digest, case),
            "warnings": advisory_warnings(digest, case),
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "source": case,
            "product": None,
            "samples": [],
            "usage": _total_usage(usages),
            "violations": [f"digest failed: {exc}"],
            "warnings": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_corpus(corpus_path, output_path, state_path=DEFAULT_PRODUCT_STATE, force=False,
               samples=1):
    with open(corpus_path, encoding="utf-8") as stream:
        corpus = json.load(stream)

    previous = {}
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as stream:
            previous = {case["id"]: case for case in json.load(stream)["cases"]}
    processed = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as stream:
            processed = json.load(stream)

    cases = []
    cached = 0
    updated_processed = {}
    for case in corpus:
        fingerprint = _case_fingerprint(case, samples)
        old = previous.get(case["id"])
        if (not force and old and old.get("fingerprint") == fingerprint
                and processed.get(case["id"]) == fingerprint
                and old.get("product") and old.get("error") is None):
            result_case = old
            cached += 1
        else:
            result_case = run_case(case, samples)
        result_case["fingerprint"] = fingerprint
        cases.append(result_case)
        if result_case["error"] is None:
            updated_processed[case["id"]] = fingerprint

    result = {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus_path,
        "variant": current_variant(),
        "samples": samples,
        "cases": cases,
        "summary": {
            "total": len(cases),
            "cached": cached,
            "successful": sum(case["error"] is None for case in cases),
            "failed": sum(case["error"] is not None for case in cases),
            "violations": sum(bool(case["violations"]) for case in cases),
            "usage": _total_usage([case.get("usage") or {} for case in cases]),
        },
    }
    parent = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    state_parent = os.path.dirname(os.path.abspath(state_path))
    os.makedirs(state_parent, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as stream:
        json.dump(updated_processed, stream, indent=2, ensure_ascii=False)
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
    parser.add_argument("--product-state", default=DEFAULT_PRODUCT_STATE)
    parser.add_argument("--force", action="store_true",
                        help="regenerate all products, ignoring the product cache")
    parser.add_argument("--model", help="override LLM_MODEL for this run")
    parser.add_argument("--reasoning", help="override LLM_REASONING_EFFORT (low/medium/high)")
    parser.add_argument("--no-structured-output", dest="structured", action="store_false",
                        default=None, help="do not ask the endpoint to enforce the JSON schema")
    parser.add_argument("--samples", type=int, default=1,
                        help="generations per case; >1 measures run-to-run stability")
    args = parser.parse_args()

    apply_llm_overrides(args.model, args.reasoning, args.structured)

    created = ensure_corpus(args.corpus, args.processed, args.limit)
    if created:
        print(f"Corpus was missing; created it at {args.corpus}")

    result = run_corpus(args.corpus, args.out, args.product_state, args.force, args.samples)
    summary = result["summary"]
    print(
        f"Wrote {summary['total']} product case(s) to {args.out}; "
        f"reused {summary['cached']} cached case(s); "
        f"{summary['violations']} case(s) have violations."
    )
    usage = summary["usage"]
    if usage:
        cost = f"${usage['cost_usd']:.4f}" if "cost_usd" in usage else "not reported"
        print(
            f"Variant {result['variant']['model'] or result['variant']['provider']}: "
            f"cost {cost}, {usage.get('total_tokens', 0)} tokens, "
            f"{usage.get('latency_s', 0):.1f}s of model time."
        )
    print("This file contains real school posts: personal data. Never commit it.")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
