"""Score digests over a real corpus and gate on the result.

Two tiers of check:

* Structural — derived from the digest alone, so they need no ground truth and
  can live in this public repo. These encode the failure modes actually
  observed: invented placeholder dates, a packing list exploded into one
  near-identical action per item, dropped dates, headings invented for a
  three-line post.
* Recall — "this digest must mention X", loaded from a local expectations file.
  Those strings quote real posts, so the file is personal data and gitignored.

Run `build_corpus.py` first. Sends no notifications.
"""
import argparse
import json
import os
import re
import sys

from get_social_schools_news import (
    _DUTCH_MONTHS,
    _extract_action_hints,
    Attachment,
    generate_digest,
    render_digest_notification,
)

DEFAULT_CORPUS = "corpus/corpus.json"
DEFAULT_RESULTS = "eval_results.json"

_PLACEHOLDER_RE = re.compile(
    r'\b(xx|tbd|n/?a|unknown date|date not specified|not specified|onbekend)\b',
    re.IGNORECASE,
)
_HINT_DATE_RE = re.compile(r'^date:\s*(\d{1,2})\s*([a-z]+)', re.IGNORECASE)
# Hints use Dutch month names, digests use English abbreviations.
_MONTH_ABBR_BY_DUTCH_PREFIX = {nl[:3].lower(): abbr for nl, abbr in _DUTCH_MONTHS.items()}

_DUPLICATE_JACCARD = 0.7
_SHARED_PREFIX_TOKENS = 4
_SHARED_PREFIX_LIMIT = 3
# A very short post has one subject; inventing headings for it is noise.
_SINGLE_TOPIC_MAX_CHARS = 400
_MAX_TOPICS = 6


def _entry_lists(digest):
    for topic in digest.topics:
        yield topic.heading, "actions", topic.actions
        yield topic.heading, "bring", topic.bring
        yield topic.heading, "notes", topic.notes


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t]


def find_placeholder_dates(digest):
    """Entries that invented a date rather than omitting one."""
    return [
        f"placeholder date in {heading or '(untitled)'}/{field}: {entry!r}"
        for heading, field, entries in _entry_lists(digest)
        for entry in entries
        if _PLACEHOLDER_RE.search(entry)
    ]


def find_near_duplicates(digest):
    """Entries that repeat each other, e.g. a packing list split one item per action."""
    violations = []
    for heading, field, entries in _entry_lists(digest):
        token_sets = [set(_tokens(e)) for e in entries]
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = token_sets[i], token_sets[j]
                if len(a) < 3 or len(b) < 3:
                    continue
                union = a | b
                if union and len(a & b) / len(union) >= _DUPLICATE_JACCARD:
                    violations.append(
                        f"near-duplicate in {heading or '(untitled)'}/{field}: "
                        f"{entries[i]!r} vs {entries[j]!r}")

        prefixes = {}
        for entry in entries:
            tokens = _tokens(entry)
            if len(tokens) >= _SHARED_PREFIX_TOKENS:
                prefixes.setdefault(tuple(tokens[:_SHARED_PREFIX_TOKENS]), []).append(entry)
        for prefix, shared in prefixes.items():
            if len(shared) >= _SHARED_PREFIX_LIMIT:
                violations.append(
                    f"{len(shared)} entries in {heading or '(untitled)'}/{field} share the "
                    f"opening {' '.join(prefix)!r} - likely a list that should be 'bring'")
    return violations


def find_missing_hint_dates(digest, body):
    """Dates the pre-scan found in the source but that reach no entry."""
    rendered = render_digest_notification(digest).lower()
    missing = []
    for hint in _extract_action_hints(body):
        match = _HINT_DATE_RE.match(hint)
        if not match:
            continue
        day, month_nl = match.group(1), match.group(2)[:3].lower()
        abbr = _MONTH_ABBR_BY_DUTCH_PREFIX.get(month_nl)
        if not abbr:
            continue
        day_pattern = re.compile(rf'\b0?{int(day)}\b')
        if not any(day_pattern.search(line) and abbr.lower() in line
                   for line in rendered.splitlines()):
            missing.append(f"source date not in digest: {int(day)} {abbr}")
    return sorted(set(missing))


def find_bring_repeated_in_actions(digest):
    """A packing item belongs in 'bring' only, never duplicated as an action."""
    violations = []
    for topic in digest.topics:
        for item in topic.bring:
            item_tokens = set(_tokens(item))
            if not item_tokens:
                continue
            for action in topic.actions:
                if item_tokens and item_tokens <= set(_tokens(action)):
                    violations.append(
                        f"bring item {item!r} is repeated in action {action!r}")
    return violations


def find_structure_problems(digest, text):
    violations = []
    if not digest.tldr.strip():
        violations.append("tldr is empty")
    if len(text) < _SINGLE_TOPIC_MAX_CHARS and len(digest.topics) > 1:
        violations.append(
            f"{len(digest.topics)} topics for a {len(text)}-char message - headings likely invented")
    if len(digest.topics) > _MAX_TOPICS:
        violations.append(f"{len(digest.topics)} topics is more than the message plausibly has")
    return violations


def source_text(case):
    """Everything the digest was given, mirroring generate_digest's hint source.

    A date or obligation stated only in a PDF is still a date the digest must
    carry, and a three-line post with a long attachment is not a short message.
    """
    return "\n".join(
        [case["body"]]
        + [a["text"] for a in case.get("attachments", []) if not a.get("failed")]
    )


def structural_violations(digest, case):
    text = source_text(case)
    return (
        find_placeholder_dates(digest)
        + find_near_duplicates(digest)
        + find_missing_hint_dates(digest, text)
        + find_bring_repeated_in_actions(digest)
        + find_structure_problems(digest, text)
    )


def score_recall(digest, expected):
    """Fraction of must-mention strings present in the rendered notification."""
    if not expected:
        return 0, 0, []
    rendered = render_digest_notification(digest).lower()
    missing = [phrase for phrase in expected if phrase.lower() not in rendered]
    return len(expected) - len(missing), len(expected), missing


def evaluate_case(case, expected, runs):
    """Run a case `runs` times and keep the worst outcome, since sampling can vary."""
    attachments = [
        Attachment(filename=a["filename"], url="", filetype=a["filetype"],
                   text=a["text"], failed=a["failed"])
        for a in case.get("attachments", [])
    ]
    worst = None
    for _ in range(max(1, runs)):
        try:
            digest = generate_digest(case["title"], case["body"], attachments)
            violations = structural_violations(digest, case)
            hits, total, missing = score_recall(digest, expected)
        except Exception as exc:
            violations, hits, total, missing = [f"digest failed: {exc}"], 0, len(expected or []), list(expected or [])
        result = {
            "id": case["id"],
            "violations": violations,
            "recall_hits": hits,
            "recall_total": total,
            "recall_missing": missing,
        }
        if worst is None or (len(violations), -hits) > (len(worst["violations"]), -worst["recall_hits"]):
            worst = result
    return worst


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--expectations", help="local JSON of {case_id: [must-mention, ...]}")
    parser.add_argument("--results", default=DEFAULT_RESULTS)
    parser.add_argument("--baseline", help="previous results file to diff against")
    parser.add_argument("--runs", type=int, default=1,
                        help="repeats per case; the worst run counts (temperature 0 is not exactly deterministic)")
    parser.add_argument("--min-recall", type=float, default=1.0)
    args = parser.parse_args()

    if not os.path.exists(args.corpus):
        sys.exit(f"No corpus at {args.corpus}. Run build_corpus.py first.")
    with open(args.corpus, encoding="utf-8") as f:
        corpus = json.load(f)

    expectations = {}
    if args.expectations:
        with open(args.expectations, encoding="utf-8") as f:
            expectations = json.load(f)

    results = [evaluate_case(case, expectations.get(case["id"], []), args.runs) for case in corpus]

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, encoding="utf-8") as f:
            baseline = {r["id"]: r for r in json.load(f)}

    failed = 0
    print(f"\n{'case':<24} {'result':<6} {'viol':>4} {'recall':>8}  detail")
    print("-" * 78)
    for result in results:
        recall_ok = (result["recall_total"] == 0
                     or result["recall_hits"] / result["recall_total"] >= args.min_recall)
        ok = not result["violations"] and recall_ok
        failed += not ok
        recall = (f"{result['recall_hits']}/{result['recall_total']}"
                  if result["recall_total"] else "-")
        detail = "; ".join(result["violations"] + [f"missing {m!r}" for m in result["recall_missing"]])
        print(f"{result['id']:<24} {'PASS' if ok else 'FAIL':<6} "
              f"{len(result['violations']):>4} {recall:>8}  {detail[:200]}")

        was = baseline.get(result["id"])
        if was and len(result["violations"]) > len(was["violations"]):
            print(f"{'':<24} REGRESSED: {len(was['violations'])} -> {len(result['violations'])} violations")

    with open(args.results, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{len(results) - failed}/{len(results)} passed. Results written to {args.results}")
    print("Results quote real posts: personal data. Never commit them.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
