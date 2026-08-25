"""Digest evaluation scoring.

Each check below encodes a failure actually observed in a delivered
notification, so these tests double as regression cases for the scorer.
"""
import json
from unittest.mock import patch

import pytest

from socialschools.models import Digest, Topic
from tools import evaluate_digests
from tools.evaluate_digests import (
    build_summary,
    closest_line,
    evaluate_product_case,
    find_actions_hidden_in_notes,
    find_meta_tldr,
    find_unfaithful_claims,
    find_unpadded_date_prefixes,
    find_untranslated_items,
    is_saturated,
    load_expectations,
    phrase_present,
    quality_score,
    score_recall,
    split_for,
    structural_violations,
)

CASE = {
    "id": "test-article",
    "title": "Test article",
    "post_date": "22 Aug 10:00",
    "body": "Test body",
    "attachments": [{
        "filename": "letter.pdf",
        "filetype": "pdf",
        "failed": False,
        "text": "Bring a hat.",
    }],
}

PRODUCT_RECORD = {
    "id": "test-article",
    "source": CASE,
    "product": {
        "digest": {
            "translated_title": "Test article",
            "tldr": "Swimming at 8:30.",
            "topics": [{"heading": "Trip", "actions": [], "bring": ["a hat"], "notes": []}],
        },
        "notification": "Swimming at 8:30.",
    },
}


def _digest(topics, tldr="Summary"):
    return Digest(translated_title="T", tldr=tldr, topics=topics)


# No title and no post date, so these tests score the digest body on its own.
# Chrome-sensitive behaviour is covered separately, against a case that has both.
PLAIN_CASE = {"body": "", "attachments": []}


# =============================================================================
# STRUCTURAL AND ADVISORY CHECKS
# =============================================================================


def test_find_placeholder_dates_flags_invented_date():
    """'XX Sep - Parent evening (date not specified)' was really emitted once"""
    digest = _digest([Topic(heading="Evening",
                            actions=["XX Sep - Parent evening (date not specified)"],
                            bring=[], notes=[])])
    assert evaluate_digests.find_placeholder_dates(digest)


def test_find_placeholder_dates_accepts_undated_entry():
    """An entry with no date at all is correct behaviour, not a placeholder"""
    digest = _digest([Topic(heading="Supplies",
                            actions=["Provide the listed school supplies"],
                            bring=[], notes=[])])
    assert evaluate_digests.find_placeholder_dates(digest) == []


def test_find_near_duplicates_flags_exploded_packing_list():
    """Nine 'Provide your child with X' actions were really emitted once"""
    digest = _digest([Topic(
        heading="Trip",
        actions=[
            "Provide your child with a towel for the school trip",
            "Provide your child with shower gel for the school trip",
            "Provide your child with dry clothes for the school trip",
        ],
        bring=[], notes=[])])
    assert evaluate_digests.find_near_duplicates(digest)


def test_find_near_duplicates_allows_genuinely_distinct_entries():
    """Similarly-shaped but distinct test dates must not be flagged"""
    digest = _digest([Topic(
        heading="Tests",
        actions=[],
        bring=[],
        notes=[
            "07 Sep - topography test tile 1",
            "11 Sep - English song 1",
            "02 Oct - English song 2",
        ])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_near_duplicates_allows_one_entry_per_group():
    """'Group 6B' and 'Group 6C' address different children, not the same one twice"""
    digest = _digest([Topic(
        heading="Class parents",
        actions=[
            "Email the class parent details for group 6B",
            "Email the class parent details for group 6C",
        ],
        bring=[], notes=[])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_near_duplicates_allows_shared_prefix_when_each_names_a_group():
    """A start-time per group repeats wording by necessity"""
    digest = _digest([Topic(
        heading="First school day",
        actions=[],
        bring=[],
        notes=[
            "18 Aug - group 3 starts at 08:30",
            "18 Aug - group 4 starts at 08:35",
            "18 Aug - group 5 starts at 08:40",
        ])])
    assert evaluate_digests.find_near_duplicates(digest) == []


def test_find_missing_hint_dates_ignores_newsletter_filler():
    """A museum listing in an attached newsletter obliges no parent"""
    body = ("Tot en met 11 oktober hangt het meisje naast haar ouders in het "
            "museum aan het Klein Heiligland.")
    digest = _digest([Topic(heading="News", actions=[], bring=[], notes=["a note"])])
    assert evaluate_digests.find_missing_hint_dates(digest, body, PLAIN_CASE) == []


def test_find_same_date_clusters_flags_one_event_split_across_many_lines():
    """A single field trip restated across arrival/departure/return lines"""
    digest = _digest([Topic(
        heading="Field Trip",
        actions=[
            "01 Sep - Ensure child arrives at school by 08:20 for the 08:30 bus.",
            "01 Sep - Inform after-school care about a possible late return.",
        ],
        bring=[],
        notes=[
            "01 Sep - Field trip to Poldersport is scheduled.",
            "01 Sep - Departure by bus from school at 08:30.",
            "01 Sep - Expected return to school around 14:30.",
        ])])
    warnings = evaluate_digests.find_same_date_clusters(digest)
    assert any("all dated '01 Sep'" in w for w in warnings)


def test_find_same_date_clusters_allows_few_entries_on_one_date():
    digest = _digest([Topic(
        heading="Trip",
        actions=["01 Sep - Sign the permission form."],
        bring=[],
        notes=["01 Sep - Bus departs at 08:30."])])
    assert evaluate_digests.find_same_date_clusters(digest) == []


def test_find_missing_hint_dates_still_flags_school_event():
    """A school trip date is the whole reason the tool exists"""
    body = "Het schoolreisje is op 1 september, we vertrekken om 08:30."
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body, PLAIN_CASE) == [
        "source date not in digest: 1 Sep"]


def test_find_structure_problems_allows_many_topics_in_a_newsletter():
    """A full school newsletter really does have a dozen sections"""
    digest = _digest([
        Topic(heading=f"Section {i}", actions=[], bring=[], notes=["a note"])
        for i in range(9)
    ])
    assert evaluate_digests.find_structure_problems(digest, "x" * 6000) == []


def test_find_structure_problems_still_caps_topics_on_a_normal_post():
    digest = _digest([
        Topic(heading=f"Section {i}", actions=[], bring=[], notes=["a note"])
        for i in range(9)
    ])
    problems = evaluate_digests.advisory_warnings(
        digest, {"body": "x" * 1000, "attachments": []})
    assert any("more than the message plausibly has" in p for p in problems)


def test_find_missing_hint_dates_flags_dropped_date():
    body = "Op dinsdag 1 september gaan wij op schoolreisje."
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body, PLAIN_CASE) == [
        "source date not in digest: 1 Sep"]


def test_find_missing_hint_dates_accepts_a_date_carried_by_the_post_date_line():
    """The parent sees the post date, so a date only in that line is not missing"""
    body = "Op dinsdag 1 september gaan wij op schoolreisje."
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    case = {"body": body, "attachments": [], "title": "Schoolreisje", "post_date": "01 Sep 09:00"}
    assert evaluate_digests.find_missing_hint_dates(digest, body, case) == []


def test_find_missing_hint_dates_passes_when_date_present():
    body = "Op dinsdag 1 september gaan wij op schoolreisje."
    digest = _digest([Topic(heading="Trip", actions=["01 Sep - school trip"], bring=[], notes=[])])
    assert evaluate_digests.find_missing_hint_dates(digest, body, PLAIN_CASE) == []


def test_find_bring_repeated_in_actions():
    digest = _digest([Topic(heading="Trip",
                            actions=["Provide a towel for the trip"],
                            bring=["towel"], notes=[])])
    assert evaluate_digests.find_bring_repeated_in_actions(digest)


def test_duplication_fails_the_gate_but_a_misfiled_note_only_warns():
    """A repeated packing item is always a defect; an imperative-sounding note is not.

    Every 'note reads like an action' on the corpus turned out to describe what
    the school does rather than ask anything of the parent.
    """
    repeated = _digest([Topic(heading="Trip", actions=["Provide a towel for the trip"],
                              bring=["towel"], notes=[])])
    reported = _digest([Topic(heading="Trip", actions=[], bring=[],
                              notes=["The teacher will contact you before the trip"])])

    assert structural_violations(repeated, PLAIN_CASE)
    assert structural_violations(reported, PLAIN_CASE) == []
    assert evaluate_digests.advisory_warnings(repeated, PLAIN_CASE) == []


def test_a_notification_too_long_to_read_is_a_violation():
    """A newsletter can hold to its topic cap and still reprint the school guide"""
    wall = _digest([Topic(heading="General", actions=[], bring=[],
                          notes=[f"Reference note number {n} about school policy"
                                 for n in range(60)])])
    brief = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])

    assert any("past the" in v
               for v in evaluate_digests.find_notification_too_long(wall, PLAIN_CASE))
    assert evaluate_digests.find_notification_too_long(brief, PLAIN_CASE) == []


def test_a_newsletter_is_allowed_a_longer_notification_than_a_short_post():
    """The source length decides the budget, as it already does for topic count"""
    digest = _digest([Topic(heading="General", actions=[], bring=[],
                            notes=[f"Reference note number {n} about school policy"
                                   for n in range(40)])])
    short_post = {"body": "x" * 500, "attachments": []}
    newsletter = {"body": "x" * 8000, "attachments": []}

    assert evaluate_digests.find_notification_too_long(digest, short_post)
    assert evaluate_digests.find_notification_too_long(digest, newsletter) == []


def test_find_structure_problems_flags_empty_tldr():
    digest = _digest([Topic(heading="T", actions=["Do it"], bring=[], notes=[])], tldr="")
    assert "tldr is empty" in evaluate_digests.find_structure_problems(digest, "body")


def test_find_structure_problems_flags_invented_headings_on_short_post():
    """A 261-char newsletter does not have three subjects"""
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    problems = evaluate_digests.find_structure_problems(digest, "short body")
    assert any("headings likely invented" in p for p in problems)


def test_find_structure_problems_allows_multiple_topics_on_long_post():
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    assert evaluate_digests.find_structure_problems(digest, "x" * 2000) == []


def test_score_recall_counts_hits_and_missing():
    digest = _digest([Topic(heading="Trip",
                            actions=["Child must have a swimming diploma"],
                            bring=[], notes=[])])
    hits, total, missing = evaluate_digests.score_recall(
        digest, PLAIN_CASE, ["swimming diploma", "08:20"])
    assert (hits, total, missing) == (1, 2, ["08:20"])


def test_score_recall_sees_the_post_date_line_the_parent_sees():
    """Scoring a rendering without the date line failed expectations that were met"""
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    case = {"body": "", "attachments": [], "title": "Schoolreisje", "post_date": "01 Sep 09:00"}
    hits, total, missing = evaluate_digests.score_recall(digest, case, ["01 Sep"])
    assert (hits, total, missing) == (1, 1, [])


def test_score_recall_with_no_expectations_is_neutral():
    digest = _digest([Topic(heading="T", actions=["Do it"], bring=[], notes=[])])
    assert evaluate_digests.score_recall(digest, PLAIN_CASE, []) == (0, 0, [])


def test_source_text_includes_attachment_content():
    """An obligation stated only in a PDF is still one the digest must carry"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "Lever het formulier in voor 15 aug."}],
    }
    assert "15 aug" in evaluate_digests.source_text(case)


def test_source_text_skips_failed_attachments():
    """A failed extraction has no text, so it cannot be held against the digest"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": True, "text": ""}],
    }
    assert evaluate_digests.source_text(case) == "Zie de bijlage."


def test_structural_violations_flag_date_found_only_in_attachment():
    case = {
        "body": "Zie de bijlage." + "x" * 500,
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "Het schoolreisje is op 1 september."}],
    }
    digest = _digest([Topic(heading="Trip", actions=["Pack a bag"], bring=[], notes=[])])
    assert evaluate_digests.structural_violations(digest, case) == []
    assert "source date not in digest: 1 Sep" in evaluate_digests.advisory_warnings(digest, case)


def test_structural_violations_allow_topics_when_attachment_is_long():
    """A short post with a long PDF is not a short message"""
    case = {
        "body": "Zie de bijlage.",
        "attachments": [{"filename": "brief.pdf", "filetype": "pdf",
                         "failed": False, "text": "y" * 2000}],
    }
    digest = _digest([
        Topic(heading="One", actions=[], bring=[], notes=["a note"]),
        Topic(heading="Two", actions=[], bring=[], notes=["another"]),
    ])
    assert evaluate_digests.structural_violations(digest, case) == []


# =============================================================================
# EXPECTATIONS, RECALL AND SCORING
# =============================================================================


def test_evaluate_product_case_does_not_generate_again():
    record = {
        "id": "test-article",
        "source": CASE,
        "product": {
            "digest": {
                "translated_title": "Test article",
                "tldr": "Bring a hat.",
                "topics": [{
                    "heading": "Trip",
                    "actions": [],
                    "bring": ["a hat"],
                    "notes": [],
                }],
            },
            "notification": "Bring a hat.",
        },
    }
    with patch("socialschools.digest.generate.generate_digest", side_effect=AssertionError):
        result = evaluate_product_case(record, [])

    assert result["id"] == "test-article"
    assert result["violations"] == []


def test_split_is_stable_and_holds_some_cases_back():
    """The tune/holdout split must be reproducible without a bookkeeping file"""
    ids = [f"post_{n}" for n in range(200)]
    splits = [split_for(case_id) for case_id in ids]
    assert splits == [split_for(case_id) for case_id in ids]
    assert set(splits) == {"tune", "holdout"}
    assert 0.1 < splits.count("holdout") / len(splits) < 0.4


def test_load_expectations_accepts_legacy_list_and_object(tmp_path):
    path = tmp_path / "expectations.json"
    path.write_text(json.dumps({
        "_meta": {"ignored": True},
        "post_legacy": ["1 Sep"],
        "post_rich": {"must_mention": ["1 Sep"], "must_not_mention": ["09:00"]},
    }), encoding="utf-8")

    expectations = load_expectations(str(path))

    assert "_meta" not in expectations
    assert expectations["post_legacy"] == {"must_mention": ["1 Sep"], "must_not_mention": []}
    assert expectations["post_rich"]["must_not_mention"] == ["09:00"]


def test_phrase_present_ignores_time_padding_and_accepts_alternatives():
    """A model writing 08:30 must not fail an expectation written as 8:30"""
    assert phrase_present("8:30", "swimming starts at 08:30")
    assert phrase_present("08:30", "swimming starts at 8:30")
    assert phrase_present("towel|handdoek", "bring a handdoek")
    assert not phrase_present("towel|handdoek", "bring a hat")


def test_phrase_present_ignores_day_padding():
    """'1 Sep' and '01 Sep' are one date, whichever side wrote which."""
    assert phrase_present("1 Sep", "01 Sep - swimming lesson")
    assert phrase_present("01 Sep", "1 Sep - swimming lesson")


def test_a_date_is_not_found_inside_a_bigger_date():
    """The failure this check exists to catch: an invented day passing as the wanted one."""
    assert not phrase_present("1 Jul", "21 Jul - sports day")
    assert not phrase_present("3 Jul", "13 Jul - report cards")
    assert not phrase_present("10 Mar", "110 Mar is not a date")
    assert not phrase_present("12:15", "the bus leaves at 12:150")


def test_a_word_expectation_still_matches_its_plural():
    """Only numbers get boundary treatment; 'towel' must still find 'towels'."""
    assert phrase_present("towel", "bring two towels")
    assert phrase_present("group 6C", "group 6Ca")


def test_score_recall_uses_normalised_matching():
    digest = Digest("t", "Swimming at 08:30", [])
    hits, total, missing = score_recall(digest, PLAIN_CASE, ["8:30", "swimming"])
    assert (hits, total, missing) == (2, 2, [])


def test_find_unfaithful_claims_flags_invented_facts():
    """Recall alone rewards saying everything; this is what punishes inventing it"""
    digest = Digest("t", "Departure at 09:00", [])
    assert find_unfaithful_claims(digest, PLAIN_CASE, ["09:00"]) == [
        "states what the message does not: '09:00'"]
    assert find_unfaithful_claims(digest, PLAIN_CASE, ["10:00"]) == []


def test_evaluate_product_case_counts_a_forbidden_phrase_as_a_violation():
    result = evaluate_product_case(
        PRODUCT_RECORD, {"must_mention": ["8:30"], "must_not_mention": ["cancelled"]})
    assert result["violations"] == []
    assert result["recall_hits"] == 1

    unfaithful = evaluate_product_case(
        PRODUCT_RECORD, {"must_mention": [], "must_not_mention": ["swimming"]})
    assert unfaithful["violations"]


def test_evaluate_product_case_reports_instability_across_samples():
    record = dict(PRODUCT_RECORD, samples=[
        PRODUCT_RECORD["product"]["digest"],
        {"translated_title": "Test article", "tldr": "Nothing here.", "topics": []},
    ])
    result = evaluate_product_case(record, {"must_mention": ["8:30"], "must_not_mention": []})

    assert result["samples"] == 2
    assert result["stable"] is False


def test_build_summary_reports_each_split_and_the_bill():
    product = {
        "variant": {"model": "cheap-model"},
        "samples": 1,
        "summary": {"usage": {"cost_usd": 0.02, "total_tokens": 900}},
    }
    results = [
        {"id": "a", "split": "tune", "violations": [], "recall_hits": 2,
         "recall_total": 2, "warnings": [], "stable": True},
        {"id": "b", "split": "holdout", "violations": ["bad"], "recall_hits": 1,
         "recall_total": 2, "warnings": ["meh"], "stable": True},
    ]
    summary = build_summary(product, results, min_recall=1.0)

    assert summary["variant"]["model"] == "cheap-model"
    assert summary["usage"]["cost_usd"] == 0.02
    assert summary["splits"]["tune"]["passed"] == 1
    assert summary["splits"]["holdout"]["passed"] == 0
    assert summary["splits"]["all"]["recall"] == 0.75


def test_quality_score_grades_warnings_below_violations():
    """Warnings must move the score, or a saturated eval cannot rank models"""
    clean = {"recall_hits": 2, "recall_total": 2, "violations": [], "warnings": []}
    noisy = {"recall_hits": 2, "recall_total": 2, "violations": [], "warnings": ["a", "b"]}
    broken = {"recall_hits": 2, "recall_total": 2, "violations": ["x"], "warnings": []}

    assert quality_score(clean) == 1.0
    assert quality_score(noisy) == pytest.approx(0.9)
    assert quality_score(broken) == pytest.approx(0.5)
    assert quality_score({"recall_hits": 0, "recall_total": 0,
                          "violations": [], "warnings": []}) == 1.0


def test_is_saturated_detects_a_gate_that_stopped_discriminating():
    assert is_saturated({"splits": {"all": {"cases": 4, "passed": 4}}}) is True
    assert is_saturated({"splits": {"all": {"cases": 4, "passed": 3}}}) is False


def test_find_meta_tldr_flags_a_summary_about_the_message():
    """'This message provides information about X' tells a parent nothing"""
    meta = Digest("t", "This message provides important information for parents.", [])
    useful = Digest("t", "School trip on 01 Sep: pack a raincoat and a packed lunch.", [])

    assert find_meta_tldr(meta)
    assert find_meta_tldr(useful) == []


def test_closest_line_shows_what_the_digest_said_instead():
    """A miss is an omission or a paraphrase, and they want opposite fixes"""
    digest = Digest("t", "Class allocation for next year is ready.",
                    [Topic(heading="Holidays", actions=[], bring=[], notes=["Summer break"])])

    assert "Class allocation" in closest_line("class division", digest, PLAIN_CASE)
    assert closest_line("unrelated wording entirely", digest, PLAIN_CASE) == ""


def test_evaluate_product_case_reports_the_nearest_line_for_a_miss():
    result = evaluate_product_case(
        PRODUCT_RECORD, {"must_mention": ["departure time"], "must_not_mention": []})

    assert result["recall_missing"] == ["departure time"]
    assert "recall_near_misses" in result


def test_find_unpadded_date_prefixes_flags_a_single_digit_day():
    """'7 Sep' beside '01 Sep' in one notification is the model ignoring the convention"""
    digest = Digest("t", "s", [Topic(heading="Tests", actions=["01 Sep - trip"],
                                     bring=[], notes=["7 Sep - topography test"])])

    problems = find_unpadded_date_prefixes(digest)

    assert len(problems) == 1
    assert "7 Sep - topography test" in problems[0]


def test_find_actions_hidden_in_notes_flags_an_instruction_filed_as_a_fact():
    """An arrival time rendered as a note sits below the actions and gets missed"""
    digest = Digest("t", "s", [Topic(
        heading="Trip", actions=[], bring=[],
        notes=["01 Sep - arrive at school by 08:20", "Children will get wet"])])

    problems = find_actions_hidden_in_notes(digest)

    assert len(problems) == 1
    assert "arrive at school" in problems[0]


# Invented stand-in for a source in the school's own language.
UNTRANSLATED_SOURCE = "Neem mee: een blauwe schrijfpen, een etui en een koptelefoon."


def test_find_untranslated_items_flags_words_copied_from_the_source():
    """A parent who cannot read the school's language cannot act on its words"""
    digest = Digest("t", "s", [Topic(
        heading="Supplies", actions=[], notes=[],
        bring=["blauwe schrijfpen", "etui", "headphones"])])

    problems = find_untranslated_items(digest, UNTRANSLATED_SOURCE)

    assert len(problems) == 2
    assert all("headphones" not in problem for problem in problems)


def test_a_whole_untranslated_list_fails_but_one_loanword_only_warns():
    """One item may legitimately share a spelling; a list of them cannot"""
    case = {"id": "c", "title": "t", "body": UNTRANSLATED_SOURCE, "attachments": []}
    one = Digest("t", "s", [Topic(heading="S", actions=[], notes=[], bring=["etui"])])
    several = Digest("t", "s", [Topic(
        heading="S", actions=[], notes=[], bring=["etui", "koptelefoon"])])

    assert structural_violations(one, case) == []
    assert len(structural_violations(several, case)) == 2
