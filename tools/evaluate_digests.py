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

Recall is literal string matching, which is right for a date and hopeless for a
translated noun. So a phrase that was not found gets one appeal: `judge.py` is
asked whether the digest conveys it in other words, and may overturn the miss.
It is never asked about a phrase that was found, and it can only ever rescue —
never fail — a case. `--no-judge` keeps a run offline and fully deterministic.

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

from rich.markup import escape

from socialschools.console import console, new_table
from socialschools.digest.hints import DUTCH_MONTHS as _DUTCH_MONTHS, extract_action_hints
from socialschools.digest.parse import dict_to_digest
from socialschools.digest.render import render_digest_notification
from socialschools.paths import (
    EVAL_SUMMARY_FILE,
    EVAL_RESULTS_FILE,
    EXPECTATIONS_FILE,
    PRODUCT_FILE,
    ensure_parent,
)

DEFAULT_PRODUCT = PRODUCT_FILE
DEFAULT_RESULTS = EVAL_RESULTS_FILE
DEFAULT_EXPECTATIONS = EXPECTATIONS_FILE
DEFAULT_SUMMARY = EVAL_SUMMARY_FILE

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

# A Digest replaces the message; it does not reproduce it. These caps come from
# the corpus: every well-formed single-subject brief sits far below the first,
# and only newsletters that reprint the school guide as notes breach the second.
# Re-derive them if the corpus grows: `make eval` prints the length that failed.
_MAX_NOTIFICATION_CHARS = 1500
_MAX_NOTIFICATION_CHARS_NEWSLETTER = 3000

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


def find_missing_hint_dates(digest, body, case):
    """Obligation-bearing source dates that reach no entry."""
    rendered = render_as_delivered(digest, case).lower()
    missing = []
    for hint in extract_action_hints(body):
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
    r'\b(arrive|hand in|inform|ensure|contact|register|sign up|pay|'
    r'drop off|pick up|wear|pack|bring)\b',
    re.IGNORECASE,
)
# Shorter than this and a verbatim match means nothing: '12', 'A4', 'gym'.
_MIN_TRANSLATED_WORD = 4


def find_untranslated_items(digest, text):
    """Bring items copied out of the source rather than translated.

    An item that survives verbatim into the digest was not translated, and the
    entire point of the digest is that a parent who cannot read the school's
    language still knows what to pack. An untranslated item is worse than a
    clumsy translation, because it cannot be acted on at all.
    """
    source = _normalise_for_match(text)
    problems = []
    for topic in digest.topics:
        for item in topic.bring:
            words = [word for word in _tokens(item)
                     if len(word) >= _MIN_TRANSLATED_WORD and not word.isdigit()]
            if words and _normalise_for_match(item) in source:
                problems.append(
                    f"bring item looks untranslated in "
                    f"{topic.heading or '(untitled)'}: {item!r}")
    return problems


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


def render_as_delivered(digest, case):
    """The notification exactly as a parent receives it.

    The evaluator used to render without the footer or the post date, so a
    date expectation was graded against text that structurally could not
    contain the date line — which quietly pushed the prompt to repeat the date
    inside entries. Scoring the delivered string keeps the measurement and the
    product the same artefact.
    """
    failed = [a["filename"] for a in case.get("attachments", []) if a.get("failed")]
    return render_digest_notification(
        digest,
        failed_attachments=failed or None,
        original_title=case.get("title"),
        post_date=case.get("post_date"),
    )


# One item could be a loanword spelled the same in both languages; a whole list
# of them cannot be, so only a pattern of them proves translation was skipped.
_UNTRANSLATED_VIOLATION_MIN = 2


def find_notification_too_long(digest, case):
    """A brief nobody will read to the end has stopped being a brief.

    Topic count was already capped, but length was not, and the two come apart:
    a newsletter can hold to twelve topics and still reproduce the whole school
    guide underneath them, one reference note at a time.
    """
    limit = (_MAX_NOTIFICATION_CHARS_NEWSLETTER
             if len(source_text(case)) >= _NEWSLETTER_MIN_CHARS
             else _MAX_NOTIFICATION_CHARS)
    length = len(render_as_delivered(digest, case))
    if length <= limit:
        return []
    return [f"notification is {length} characters, past the {limit} a parent will read"]


def structural_violations(digest, case):
    text = source_text(case)
    untranslated = find_untranslated_items(digest, text)
    return (
        find_placeholder_dates(digest)
        # Both are duplication rather than judgement calls: an item in 'bring'
        # that is also an action reaches the parent twice, and an instruction
        # filed as a note renders below the actions and gets missed.
        + find_bring_repeated_in_actions(digest)
        + find_actions_hidden_in_notes(digest)
        + find_notification_too_long(digest, case)
        + (untranslated if len(untranslated) >= _UNTRANSLATED_VIOLATION_MIN else [])
        + [problem for problem in find_structure_problems(digest, text)
           if "tldr is empty" in problem]
    )


def advisory_warnings(digest, case):
    """Signals worth reviewing, but too context-dependent to fail the cycle."""
    text = source_text(case)
    untranslated = find_untranslated_items(digest, text)
    return (
        find_near_duplicates(digest)
        + find_same_date_clusters(digest)
        + find_missing_hint_dates(digest, text, case)
        + find_meta_tldr(digest)
        + find_unpadded_date_prefixes(digest)
        + (untranslated if len(untranslated) < _UNTRANSLATED_VIOLATION_MIN else [])
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
    # Same for a bare leading number: '1 Sep' and '01 Sep' are one date. Padding
    # both sides is what stops '1 Jul' being found inside '21 Jul'.
    lowered = re.sub(r'(?<![\d:.])(\d)(?=\s+[^\W\d_])', r'0\1', lowered)
    return " ".join(lowered.split())


def _match_pattern(phrase):
    """A number in an expectation must be that number, not the tail of a bigger one."""
    normalised = _normalise_for_match(phrase)
    if not normalised:
        return None
    before = r'(?<!\d)' if normalised[0].isdigit() else ''
    after = r'(?!\d)' if normalised[-1].isdigit() else ''
    return re.compile(before + re.escape(normalised) + after)


def phrase_present(phrase, text):
    """Whether any '|'-separated alternative of this phrase appears in the text."""
    haystack = _normalise_for_match(text)
    patterns = [_match_pattern(alt) for alt in phrase.split("|") if alt.strip()]
    return any(pattern.search(haystack) for pattern in patterns if pattern)


def closest_line(phrase, digest, case):
    """The digest line most like a phrase it failed to carry.

    A miss is either an omission or an acceptable paraphrase, and the two want
    opposite fixes: mend the prompt, or widen the expectation. Showing what the
    digest said instead makes that call without opening the product file.
    """
    wanted = set(_tokens(phrase.replace("|", " ")))
    if not wanted:
        return ""
    best, overlap = "", 0
    for line in render_as_delivered(digest, case).splitlines():
        shared = len(wanted & set(_tokens(line)))
        if shared > overlap:
            best, overlap = line.strip(), shared
    return best


def score_recall(digest, case, expected):
    """Fraction of must-mention phrases present in the delivered notification."""
    if not expected:
        return 0, 0, []
    rendered = render_as_delivered(digest, case)
    missing = [phrase for phrase in expected if not phrase_present(phrase, rendered)]
    return len(expected) - len(missing), len(expected), missing


def find_unfaithful_claims(digest, case, forbidden):
    """Must-not-mention phrases the digest states anyway.

    These are the expensive failures: a time the message never gave, an
    obligation that was optional, a group that was not addressed.
    """
    if not forbidden:
        return []
    rendered = render_as_delivered(digest, case)
    return [f"states what the message does not: {phrase!r}"
            for phrase in forbidden if phrase_present(phrase, rendered)]


def _score_one(digest, case, expected):
    violations = structural_violations(digest, case)
    violations += find_unfaithful_claims(digest, case, expected["must_not_mention"])
    hits, total, missing = score_recall(digest, case, expected["must_mention"])
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

    digest = dict_to_digest(record["product"]["digest"])
    violations, hits, total, missing = _score_one(digest, case, expected)

    # Extra samples exist only to separate a real difference from sampling luck.
    sample_scores = []
    for raw in record.get("samples") or []:
        sample_violations, sample_hits, _, _ = _score_one(
            dict_to_digest(raw), case, expected)
        sample_scores.append({"violations": len(sample_violations), "recall_hits": sample_hits})

    return {
        "id": record["id"],
        "split": split,
        "violations": violations,
        "recall_hits": hits,
        "recall_total": total,
        "recall_missing": missing,
        "recall_near_misses": {phrase: closest_line(phrase, digest, case) for phrase in missing},
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


def apply_rescues(results, notifications, judge_fn):
    """Let a second opinion overturn a miss the string matcher could not forgive.

    Only misses are ever put to it, and a verdict can only turn a miss into a hit
    — so a judge that is wrong, absent or offline can never fail a case that
    deterministic matching passed.
    """
    for result in results:
        if not result["recall_missing"]:
            continue
        verdict = judge_fn(notifications.get(result["id"], ""), list(result["recall_missing"]))
        rescued = [phrase for phrase in result["recall_missing"] if verdict.get(phrase)]
        if not rescued:
            continue
        result["recall_rescued"] = rescued
        result["recall_hits"] += len(rescued)
        result["recall_missing"] = [phrase for phrase in result["recall_missing"]
                                    if phrase not in rescued]
    return results


def _case_detail(result):
    near = result.get("recall_near_misses") or {}
    items = list(result["violations"])
    for phrase in result["recall_missing"]:
        instead = near.get(phrase)
        items.append(f"missing {phrase!r}" + (f" (digest says: {instead!r})" if instead else ""))
    for phrase in result.get("recall_rescued") or []:
        items.append(f"judged present in other words: {phrase!r}")
    if not result["stable"]:
        items.append(f"unstable across {result['samples']} samples")
    if result.get("warnings"):
        items.append(f"warnings: {len(result['warnings'])}")
    return "; ".join(items)


def print_case_table(results, baseline, min_recall):
    table = new_table(
        "case", "split", ("result", "center"), ("viol", "right"), ("recall", "right"), "detail",
        title="Cases",
    )
    for result in results:
        ok = case_passed(result, min_recall)
        recall = (f"{result['recall_hits']}/{result['recall_total']}"
                  if result["recall_total"] else "-")
        was = baseline.get(result["id"])
        regressed = was and len(result["violations"]) > len(was["violations"])
        # Detail quotes scraped text, which may contain brackets rich would read as markup.
        detail = escape(_case_detail(result)[:320])
        if regressed:
            detail = (f"[alarm]REGRESSED {len(was['violations'])} -> "
                      f"{len(result['violations'])} violations[/alarm] {detail}")
        table.add_row(
            escape(result["id"]),
            f"[muted]{result['split']}[/muted]",
            "[ok]PASS[/ok]" if ok else "[bad]FAIL[/bad]",
            str(len(result["violations"])) if not result["violations"]
            else f"[bad]{len(result['violations'])}[/bad]",
            recall,
            detail,
        )
    console.print(table)


def _split_row(name, block):
    recall = f"{block['recall']:.0%}" if block["recall"] is not None else "n/a"
    complete = block["passed"] == block["cases"]
    return [
        name if name != "holdout" else "[head]holdout[/head]",
        f"{'[ok]' if complete else '[bad]'}{block['passed']}/{block['cases']}"
        f"{'[/ok]' if complete else '[/bad]'}",
        f"{block['score']:.2f}",
        recall,
        f"[bad]{block['violations']}[/bad]" if block["violations"] else "0",
        f"[warn]{block['warnings']}[/warn]" if block["warnings"] else "0",
        f"[warn]{block['unstable']}[/warn]" if block["unstable"] else "0",
    ]


def print_summary(summary):
    table = new_table("split", ("passed", "right"), ("score", "right"), ("recall", "right"),
                      ("viol", "right"), ("warn", "right"), ("unstable", "right"),
                      title="Summary")
    for name in ("tune", "holdout", "all"):
        block = summary["splits"][name]
        if block["cases"]:
            table.add_row(*_split_row(name, block))
    console.print(table)

    usage = summary["usage"]
    if usage.get("cost_usd") is not None:
        console.print(f"[money]${usage['cost_usd']:.4f}[/money] for "
                      f"{summary['splits']['all']['cases']} case(s) "
                      f"[muted]({usage.get('total_tokens', 0)} tokens)[/muted]")
    if is_saturated(summary):
        overall = summary["splits"]["all"]
        console.print(
            f"\n[warn]Every case passes, so the gate can no longer tell two models apart.[/warn] "
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
    parser.add_argument("--no-judge", dest="judge", action="store_false", default=True,
                        help="skip the second opinion on missed phrases (offline, fully deterministic)")
    parser.add_argument("--judge-model",
                        help="model that rules on a missed phrase (default: the configured one)")
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

    if args.judge and any(result["recall_missing"] for result in results):
        from tools.judge import DEFAULT_CACHE, load_cache, save_cache, verdicts

        cache = load_cache(DEFAULT_CACHE)
        notifications = {case["id"]: (case.get("product") or {}).get("notification", "")
                         for case in product["cases"]}
        console.print("[muted]Asking a second opinion on the phrases that were not found…[/muted]")
        apply_rescues(results, notifications,
                      lambda text, phrases: verdicts(text, phrases, args.judge_model, cache))
        save_cache(cache, DEFAULT_CACHE)

    print_case_table(results, baseline, args.min_recall)

    summary = build_summary(product, results, args.min_recall)
    with open(ensure_parent(args.results), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    if args.summary:
        with open(ensure_parent(args.summary), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    print_summary(summary)
    console.print(f"\n[muted]Results written to {args.results}"
                  + (f", scorecard to {args.summary}" if args.summary else "") + "[/muted]")
    console.print("[warn]Results quote real posts: personal data. Never commit them.[/warn]")
    gate = summary["splits"][args.gate_on]
    sys.exit(1 if gate["passed"] < gate["cases"] else 0)


if __name__ == "__main__":
    main()
