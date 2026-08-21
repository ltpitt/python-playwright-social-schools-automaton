"""Score digests over a real corpus and gate on the result.

Two tiers of check:

* Structural — derived from the digest alone, so they need no ground truth and
  can live in this public repo. These encode the failure modes actually
  observed: invented placeholder dates, a packing list exploded into one
  near-identical action per item, dropped dates, headings invented for a
  three-line post.
* Recall — "this digest must mention X", loaded from a local expectations file.
  Those strings quote real posts, so the file is personal data and gitignored.

Run `run_digest.py` first. Sends no notifications.
"""
import argparse
import json
import os
import re
import sys

from get_social_schools_news import (
    _DUTCH_MONTHS,
    _dict_to_digest,
    _extract_action_hints,
    render_digest_notification,
)

DEFAULT_PRODUCT = "eval_output/product.json"
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
# A school newsletter genuinely has many sections, so the topic cap lifts for one.
_NEWSLETTER_MIN_CHARS = 4000
_MAX_TOPICS_NEWSLETTER = 12

# Attachments are newsletters as often as they are class letters, and a
# newsletter is full of dates that oblige nobody: sports results, museum
# openings, city festivals, its own issue date. A date only counts as one the
# digest must carry when it is asked of the reader, or is a school event the
# child takes part in.
_OBLIGATION_CUE_RE = re.compile(
    r'\b('
    r'moet\w*|graag|gelieve|lever\w*|inlever\w*|meenem\w*|neem mee|meebreng\w*|'
    r'denk aan|vergeet niet|aanmeld\w*|inschrijv\w*|opgeven|opgave|doorgeven|'
    r'invullen|retourner\w*|betal\w*|uiterlijk|deadline|verzoek\w*|aanwezig|'
    r'verwacht\w*|houd rekening|let op|svp|a\.?u\.?b'
    r'|schoolreis\w*|excursie\w*|kamp|schoolkamp|ouderavond\w*|informatieavond\w*|'
    r'rapportgesprek\w*|oudergesprek\w*|tienminuten\w*|studiedag\w*|vrije dag|'
    r'vakantie\w*|margedag\w*|gymles\w*|zwemles\w*|toets\w*|proefwerk\w*|'
    r'schoolfotograaf|luizencontrole|sportdag\w*|koningsspelen|juffendag|'
    r'meesterdag|voorstelling\w*|musical\w*|open dag|eerste schooldag|'
    r'start\w* het schooljaar'
    r')\b',
    re.IGNORECASE,
)
_OBLIGATION_WINDOW = 200


def _entry_lists(digest):
    for topic in digest.topics:
        yield topic.heading, "actions", topic.actions
        yield topic.heading, "bring", topic.bring
        yield topic.heading, "notes", topic.notes


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t]


def _identifiers(text):
    """Tokens carrying a digit: '6b', '18', '08:30' - group names, dates, times."""
    return frozenset(m.lower() for m in re.findall(r"[a-zA-Z]*\d[a-zA-Z0-9:]*", text))


def _differ_by_number(entries):
    """True when every entry carries its own identifier, e.g. one per group or date.

    'Group 6B ...' and 'Group 6C ...' look near-identical as bags of words but
    address different children, so they are not a repetition to collapse.
    """
    seen = [_identifiers(e) for e in entries]
    return all(seen) and len(set(seen)) == len(seen)


def find_placeholder_dates(digest):
    """Entries that invented a date rather than omitting one."""
    return [
        f"placeholder date in {heading or '(untitled)'}/{field}: {entry!r}"
        for heading, field, entries in _entry_lists(digest)
        for entry in entries
        if _PLACEHOLDER_RE.search(entry)
    ]


def _overlapping_pairs(entries, label):
    token_sets = [set(_tokens(e)) for e in entries]
    violations = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = token_sets[i], token_sets[j]
            if len(a) < 3 or len(b) < 3 or _differ_by_number([entries[i], entries[j]]):
                continue
            if len(a & b) / len(a | b) >= _DUPLICATE_JACCARD:
                violations.append(
                    f"near-duplicate in {label}: {entries[i]!r} vs {entries[j]!r}")
    return violations


def _shared_openings(entries, label):
    prefixes = {}
    for entry in entries:
        tokens = _tokens(entry)
        if len(tokens) >= _SHARED_PREFIX_TOKENS:
            prefixes.setdefault(tuple(tokens[:_SHARED_PREFIX_TOKENS]), []).append(entry)
    return [
        f"{len(shared)} entries in {label} share the opening "
        f"{' '.join(prefix)!r} - likely a list that should be 'bring'"
        for prefix, shared in prefixes.items()
        if len(shared) >= _SHARED_PREFIX_LIMIT and not _differ_by_number(shared)
    ]


def find_near_duplicates(digest):
    """Entries that repeat each other, e.g. a packing list split one item per action."""
    violations = []
    for heading, field, entries in _entry_lists(digest):
        label = f"{heading or '(untitled)'}/{field}"
        violations += _overlapping_pairs(entries, label)
        violations += _shared_openings(entries, label)
    return violations


def _date_is_obligation(body, day, month_nl):
    """Whether any mention of this date sits in a sentence that asks something."""
    pattern = re.compile(rf'\b0?{int(day)}\s*{re.escape(month_nl)}\w*', re.IGNORECASE)
    for match in pattern.finditer(body):
        window = body[max(0, match.start() - _OBLIGATION_WINDOW):
                      match.end() + _OBLIGATION_WINDOW]
        if _OBLIGATION_CUE_RE.search(window):
            return True
    return False


def find_missing_hint_dates(digest, body):
    """Obligation-bearing source dates that reach no entry."""
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
        if not _date_is_obligation(body, day, month_nl):
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
    max_topics = _MAX_TOPICS_NEWSLETTER if len(text) >= _NEWSLETTER_MIN_CHARS else _MAX_TOPICS
    if len(digest.topics) > max_topics:
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


def evaluate_product_case(record, expected):
    """Evaluate one already-generated product without calling the model."""
    case = record["source"]
    if not record.get("product"):
        violations = record.get("violations") or ["product has no digest"]
        return {
            "id": record["id"],
            "violations": violations,
            "recall_hits": 0,
            "recall_total": len(expected or []),
            "recall_missing": list(expected or []),
        }

    digest = _dict_to_digest(record["product"]["digest"])
    violations = structural_violations(digest, case)
    hits, total, missing = score_recall(digest, expected)
    return {
        "id": record["id"],
        "violations": violations,
        "recall_hits": hits,
        "recall_total": total,
        "recall_missing": missing,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", default=DEFAULT_PRODUCT)
    parser.add_argument("--expectations", help="local JSON of {case_id: [must-mention, ...]}")
    parser.add_argument("--results", default=DEFAULT_RESULTS)
    parser.add_argument("--baseline", help="previous results file to diff against")
    parser.add_argument("--min-recall", type=float, default=1.0)
    args = parser.parse_args()

    if not os.path.exists(args.product):
        sys.exit(f"No product at {args.product}. Run make product first.")
    with open(args.product, encoding="utf-8") as f:
        product = json.load(f)

    expectations = {}
    if args.expectations:
        with open(args.expectations, encoding="utf-8") as f:
            expectations = json.load(f)

    results = [
        evaluate_product_case(case, expectations.get(case["id"], []))
        for case in product["cases"]
    ]

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
