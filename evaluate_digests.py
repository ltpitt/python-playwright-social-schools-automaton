"""Score digests over a real corpus and gate on the result.

Three tiers of check:

* Structural — derived from the digest alone, so they need no ground truth and
  can live in this public repo. These encode the failure modes actually
  observed: invented placeholder dates, a packing list exploded into one
  near-identical action per item, dropped dates, headings invented for a
  three-line post.
* Recall — "this digest must mention X", loaded from a local expectations file.
* Faithfulness — "this digest must NOT say X", from the same file. Recall alone
  rewards a model that says everything, including things the message never said;
  a wrong time or an invented obligation is the costliest failure here.

Expectation strings and the posts they quote are personal data, so that file is
gitignored.

Cases are split deterministically into a tuning set and a holdout set. The
expectations were written by looking at failures, so a score over them is
partly a score of one's own hindsight; only the holdout number says whether a
change generalises.

Run `run_digest.py` first. Sends no notifications.
"""
import argparse
import hashlib
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
DEFAULT_EXPECTATIONS = "expectations.json"

# One case in four is held out. Small corpus, so the holdout is small too — it is
# a smoke test against overfitting, not a statistically comfortable sample.
_HOLDOUT_EVERY = 4

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
_SAME_DATE_CLUSTER_LIMIT = 3
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
# Matches the digest's own date-prefix convention, "DD Mon - ...".
_ENTRY_DATE_RE = re.compile(r'^(\d{1,2}\s+[A-Za-z]{3})\s*-\s*')


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


def find_same_date_clusters(digest):
    """Many entries under one topic sharing one date, e.g. a single event split

    across several near-duplicate action/note lines instead of one entry
    (arrival time as an action, departure time as a note, return time as
    another note - all really one field trip)."""
    violations = []
    for topic in digest.topics:
        by_date = {}
        for entry in topic.actions + topic.notes:
            match = _ENTRY_DATE_RE.match(entry)
            if match:
                by_date.setdefault(match.group(1), []).append(entry)
        for entry_date, entries in by_date.items():
            if len(entries) >= _SAME_DATE_CLUSTER_LIMIT:
                violations.append(
                    f"{len(entries)} entries in {topic.heading or '(untitled)'} are all "
                    f"dated {entry_date!r} - consider consolidating into fewer entries")
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


# A tldr that describes the message instead of summarising it. The parent who
# reads only this line learns nothing, which defeats the point of the line.
_META_TLDR_RE = re.compile(
    r'\b(this (message|post|letter|newsletter|article)|'
    r'the (message|post|letter) (provides|contains|informs)|'
    r'provides (important )?information|informs parents|outlines several)\b',
    re.IGNORECASE,
)


# The digest's own date convention is a zero-padded two-digit day, so '7 Sep'
# sitting beside '01 Sep' in the same notification is just untidy.
_UNPADDED_ENTRY_DATE_RE = re.compile(r'^\d\s+[A-Za-z]{3}\s*-\s')
# A note that tells the reader to be somewhere or do something is an action in
# the wrong list, which buries it: notes render as '·', below the '▸' actions.
_ACTION_IN_NOTE_RE = re.compile(
    r'\b(arrive|arrival|hand in|inform|ensure|contact|register|sign up|pay|'
    r'drop off|pick up|wear|pack|bring)\b',
    re.IGNORECASE,
)


def find_unpadded_date_prefixes(digest):
    """Entries dated '7 Sep' where the convention, and their neighbours, use '07 Sep'."""
    return [
        f"date prefix is not zero-padded in {heading or '(untitled)'}/{field}: {entry!r}"
        for heading, field, entries in _entry_lists(digest)
        for entry in entries
        if _UNPADDED_ENTRY_DATE_RE.match(entry)
    ]


def find_actions_hidden_in_notes(digest):
    """Instructions filed as notes, where they render below the actions and get missed."""
    return [
        f"note reads like an action in {topic.heading or '(untitled)'}: {note!r}"
        for topic in digest.topics
        for note in topic.notes
        if _ACTION_IN_NOTE_RE.search(note)
    ]


def find_meta_tldr(digest):
    """A tldr that talks about the message rather than saying what happens."""
    if _META_TLDR_RE.search(digest.tldr):
        return [f"tldr describes the message instead of summarising it: {digest.tldr!r}"]
    return []


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
        + [problem for problem in find_structure_problems(digest, text)
           if "tldr is empty" in problem]
    )


def advisory_warnings(digest, case):
    """Signals worth reviewing, but too context-dependent to fail the cycle."""
    text = source_text(case)
    return (
        find_near_duplicates(digest)
        + find_same_date_clusters(digest)
        + find_missing_hint_dates(digest, text)
        + find_bring_repeated_in_actions(digest)
        + find_meta_tldr(digest)
        + find_unpadded_date_prefixes(digest)
        + find_actions_hidden_in_notes(digest)
        + [problem for problem in find_structure_problems(digest, text)
           if "tldr is empty" not in problem]
    )


def split_for(case_id):
    """Assign a case to 'tune' or 'holdout', stably and without a bookkeeping file."""
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16)
    return "holdout" if bucket % _HOLDOUT_EVERY == 0 else "tune"


def load_expectations(path):
    """Read the local expectations file, accepting the plain-list legacy form.

    A value may be a list of must-mention phrases, or an object also carrying
    must_not_mention. A phrase may offer alternatives separated by '|', so an
    acceptable paraphrase does not count as a miss.
    """
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as stream:
        raw = json.load(stream)
    expectations = {}
    for case_id, value in raw.items():
        if case_id.startswith("_"):
            continue
        if isinstance(value, list):
            value = {"must_mention": value}
        expectations[case_id] = {
            "must_mention": list(value.get("must_mention", [])),
            "must_not_mention": list(value.get("must_not_mention", [])),
        }
    return expectations


def _normalise_for_match(text):
    """Fold away differences that are formatting, not meaning."""
    lowered = text.lower()
    # '8:30' and '08:30' are the same time; the digest zero-pads, sources vary.
    lowered = re.sub(r'(?<![\d:])(\d):(\d{2})', r'0\1:\2', lowered)
    return " ".join(lowered.split())


def phrase_present(phrase, text):
    """Whether any '|'-separated alternative of this phrase appears in the text."""
    haystack = _normalise_for_match(text)
    return any(_normalise_for_match(alt) in haystack
               for alt in phrase.split("|") if alt.strip())


def closest_line(phrase, digest):
    """The digest line most like a phrase it failed to carry.

    A miss is either an omission or an acceptable paraphrase, and the two want
    opposite fixes: mend the prompt, or widen the expectation. Showing what the
    digest said instead makes that call without opening the product file.
    """
    wanted = set(_tokens(phrase.replace("|", " ")))
    if not wanted:
        return ""
    best, overlap = "", 0
    for line in render_digest_notification(digest).splitlines():
        shared = len(wanted & set(_tokens(line)))
        if shared > overlap:
            best, overlap = line.strip(), shared
    return best


def score_recall(digest, expected):
    """Fraction of must-mention phrases present in the rendered notification."""
    if not expected:
        return 0, 0, []
    rendered = render_digest_notification(digest)
    missing = [phrase for phrase in expected if not phrase_present(phrase, rendered)]
    return len(expected) - len(missing), len(expected), missing


def find_unfaithful_claims(digest, forbidden):
    """Must-not-mention phrases the digest states anyway.

    These are the expensive failures: a time the message never gave, an
    obligation that was optional, a group that was not addressed.
    """
    if not forbidden:
        return []
    rendered = render_digest_notification(digest)
    return [f"states what the message does not: {phrase!r}"
            for phrase in forbidden if phrase_present(phrase, rendered)]


def _score_one(digest, case, expected):
    violations = structural_violations(digest, case)
    violations += find_unfaithful_claims(digest, expected["must_not_mention"])
    hits, total, missing = score_recall(digest, expected["must_mention"])
    return violations, hits, total, missing


def evaluate_product_case(record, expected):
    """Evaluate one already-generated product without calling the model."""
    case = record["source"]
    expected = expected or {}
    expected = {
        "must_mention": list(expected.get("must_mention", []))
        if isinstance(expected, dict) else list(expected),
        "must_not_mention": list(expected.get("must_not_mention", []))
        if isinstance(expected, dict) else [],
    }
    split = split_for(record["id"])
    if not record.get("product"):
        violations = record.get("violations") or ["product has no digest"]
        return {
            "id": record["id"],
            "split": split,
            "violations": violations,
            "recall_hits": 0,
            "recall_total": len(expected["must_mention"]),
            "recall_missing": list(expected["must_mention"]),
            "recall_near_misses": {},
            "warnings": record.get("warnings", []),
            "samples": 0,
            "sample_scores": [],
            "stable": True,
        }

    digest = _dict_to_digest(record["product"]["digest"])
    violations, hits, total, missing = _score_one(digest, case, expected)

    # Extra samples exist only to separate a real difference from sampling luck.
    sample_scores = []
    for raw in record.get("samples") or []:
        sample_violations, sample_hits, _, _ = _score_one(
            _dict_to_digest(raw), case, expected)
        sample_scores.append({"violations": len(sample_violations), "recall_hits": sample_hits})

    return {
        "id": record["id"],
        "split": split,
        "violations": violations,
        "recall_hits": hits,
        "recall_total": total,
        "recall_missing": missing,
        "recall_near_misses": {phrase: closest_line(phrase, digest) for phrase in missing},
        "warnings": advisory_warnings(digest, case),
        "samples": len(sample_scores),
        "sample_scores": sample_scores,
        "stable": len({(s["violations"], s["recall_hits"]) for s in sample_scores}) <= 1,
    }


def _split_summary(results, min_recall):
    hits = sum(r["recall_hits"] for r in results)
    total = sum(r["recall_total"] for r in results)
    passed = sum(1 for r in results if case_passed(r, min_recall))
    scores = [quality_score(r) for r in results]
    return {
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "recall_hits": hits,
        "recall_total": total,
        "recall": round(hits / total, 3) if total else None,
        "violations": sum(len(r["violations"]) for r in results),
        "warnings": sum(len(r["warnings"]) for r in results),
        "unstable": sum(1 for r in results if not r["stable"]),
    }


def case_passed(result, min_recall):
    recall_ok = (result["recall_total"] == 0
                 or result["recall_hits"] / result["recall_total"] >= min_recall)
    return not result["violations"] and recall_ok


# Once every case passes, pass/fail can no longer rank two models — and ranking
# models is the whole point of generating products. These weights turn the same
# evidence into a graded score: a violation costs ten warnings, because a
# violation is a proven defect and a warning is only a suspicion.
_VIOLATION_PENALTY = 0.5
_WARNING_PENALTY = 0.05


def quality_score(result):
    """Graded 0-1 quality for one case, so models stay comparable at a 100% pass rate."""
    recall = (result["recall_hits"] / result["recall_total"]
              if result["recall_total"] else 1.0)
    penalty = (_VIOLATION_PENALTY * len(result["violations"])
               + _WARNING_PENALTY * len(result["warnings"]))
    return max(0.0, recall - penalty)


def is_saturated(summary):
    """Whether the gate has stopped discriminating, leaving only the score to."""
    overall = summary["splits"]["all"]
    return bool(overall["cases"]) and overall["passed"] == overall["cases"]


def build_summary(product, results, min_recall):
    """Machine-readable scorecard: what this variant achieved and what it cost."""
    by_split = {"tune": [], "holdout": []}
    for result in results:
        by_split[result["split"]].append(result)
    return {
        "variant": product.get("variant", {}),
        "samples": product.get("samples", 1),
        "usage": product.get("summary", {}).get("usage", {}),
        "min_recall": min_recall,
        "splits": {
            "all": _split_summary(results, min_recall),
            "tune": _split_summary(by_split["tune"], min_recall),
            "holdout": _split_summary(by_split["holdout"], min_recall),
        },
    }


def _case_detail(result):
    near = result.get("recall_near_misses") or {}
    items = list(result["violations"])
    for phrase in result["recall_missing"]:
        instead = near.get(phrase)
        items.append(f"missing {phrase!r}" + (f" (digest says: {instead!r})" if instead else ""))
    if not result["stable"]:
        items.append(f"unstable across {result['samples']} samples")
    if result.get("warnings"):
        items.append(f"warnings: {len(result['warnings'])}")
    return "; ".join(items)


def print_case_table(results, baseline, min_recall):
    print(f"\n{'case':<24} {'split':<8} {'result':<6} {'viol':>4} {'recall':>8}  detail")
    print("-" * 86)
    for result in results:
        ok = case_passed(result, min_recall)
        recall = (f"{result['recall_hits']}/{result['recall_total']}"
                  if result["recall_total"] else "-")
        print(f"{result['id']:<24} {result['split']:<8} {'PASS' if ok else 'FAIL':<6} "
              f"{len(result['violations']):>4} {recall:>8}  {_case_detail(result)[:320]}")

        was = baseline.get(result["id"])
        if was and len(result["violations"]) > len(was["violations"]):
            print(f"{'':<24} REGRESSED: "
                  f"{len(was['violations'])} -> {len(result['violations'])} violations")


def print_summary(summary):
    print()
    for name in ("tune", "holdout", "all"):
        block = summary["splits"][name]
        if not block["cases"]:
            continue
        recall = f"{block['recall']:.0%}" if block["recall"] is not None else "n/a"
        print(f"{name:<8} {block['passed']}/{block['cases']} passed, score {block['score']:.2f}, "
              f"recall {recall}, {block['violations']} violation(s), "
              f"{block['warnings']} warning(s)"
              + (f", {block['unstable']} unstable" if block["unstable"] else ""))
    usage = summary["usage"]
    if usage.get("cost_usd") is not None:
        print(f"cost     ${usage['cost_usd']:.4f} for {summary['splits']['all']['cases']} case(s) "
              f"({usage.get('total_tokens', 0)} tokens)")
    if is_saturated(summary):
        overall = summary["splits"]["all"]
        print(f"\nEvery case passes, so the gate can no longer tell two models apart. "
              f"The remaining signal is the score ({overall['score']:.2f}) and the "
              f"{overall['warnings']} warning(s). To make the gate discriminate again, add "
              f"must_not_mention phrases and expectations for what is still being missed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", default=DEFAULT_PRODUCT)
    parser.add_argument("--expectations", default=DEFAULT_EXPECTATIONS,
                        help="local JSON of {case_id: [must-mention, ...]}")
    parser.add_argument("--results", default=DEFAULT_RESULTS)
    parser.add_argument("--summary", help="write the machine-readable scorecard here")
    parser.add_argument("--baseline", help="previous results file to diff against")
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--gate-on", choices=["all", "tune", "holdout"], default="all",
                        help="which split decides the exit code")
    args = parser.parse_args()

    if not os.path.exists(args.product):
        sys.exit(f"No product at {args.product}. Run make product first.")
    with open(args.product, encoding="utf-8") as f:
        product = json.load(f)

    expectations = load_expectations(args.expectations)
    results = [
        evaluate_product_case(case, expectations.get(case["id"], {}))
        for case in product["cases"]
    ]

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, encoding="utf-8") as f:
            baseline = {r["id"]: r for r in json.load(f)}

    print_case_table(results, baseline, args.min_recall)

    summary = build_summary(product, results, args.min_recall)
    with open(args.results, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    if args.summary:
        os.makedirs(os.path.dirname(os.path.abspath(args.summary)), exist_ok=True)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    print_summary(summary)
    print(f"\nResults written to {args.results}"
          + (f", scorecard to {args.summary}" if args.summary else ""))
    print("Results quote real posts: personal data. Never commit them.")
    gate = summary["splits"][args.gate_on]
    sys.exit(1 if gate["passed"] < gate["cases"] else 0)


if __name__ == "__main__":
    main()
