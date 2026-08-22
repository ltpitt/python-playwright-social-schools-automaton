import json
from unittest.mock import patch

import pytest

from get_social_schools_news import Digest, Topic
from build_corpus import update_corpus
from bakeoff import format_verdict, parse_variant
from evaluate_digests import (
    build_summary,
    evaluate_product_case,
    find_unfaithful_claims,
    load_expectations,
    phrase_present,
    score_recall,
    split_for,
)
from run_digest import _case_fingerprint, apply_llm_overrides, run_case, run_corpus


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


def test_run_case_keeps_source_and_product():
    digest = Digest(
        translated_title="Test article",
        tldr="Bring a hat.",
        topics=[Topic(heading="Trip", actions=[], bring=["a hat"], notes=[])],
    )
    with patch("run_digest.generate_digest", return_value=digest), \
            patch("run_digest.structural_violations", return_value=[]):
        result = run_case(CASE)

    assert result["source"] == CASE
    assert result["product"]["digest"]["tldr"] == "Bring a hat."
    assert "Bring: a hat" in result["product"]["notification"]
    assert result["error"] is None


def test_run_case_records_generation_failure():
    with patch("run_digest.generate_digest", side_effect=RuntimeError("model down")):
        result = run_case(CASE)

    assert result["product"] is None
    assert result["error"] == "RuntimeError: model down"
    assert result["violations"] == ["digest failed: model down"]


def test_run_corpus_writes_json_product(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    output_path = tmp_path / "product.json"
    corpus_path.write_text(json.dumps([CASE]), encoding="utf-8")
    digest = Digest("Test article", "Summary", [])

    with patch("run_digest.generate_digest", return_value=digest), \
            patch("run_digest.structural_violations", return_value=[]):
        result = run_corpus(str(corpus_path), str(output_path))

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["summary"]["total"] == 1
    assert result["summary"]["cached"] == 0
    assert result["summary"]["successful"] == 1
    assert result["summary"]["failed"] == 0
    assert result["summary"]["violations"] == 0
    assert saved["cases"][0]["source"]["id"] == "test-article"
    assert saved["cases"][0]["product"]["digest"]["translated_title"] == "Test article"


def test_run_corpus_reuses_unchanged_product(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    output_path = tmp_path / "product.json"
    state_path = tmp_path / "processed-products.json"
    corpus_path.write_text(json.dumps([CASE]), encoding="utf-8")
    digest = Digest("Test article", "Summary", [])

    with patch("run_digest.generate_digest", return_value=digest) as generate:
        first = run_corpus(str(corpus_path), str(output_path), str(state_path))
        second = run_corpus(str(corpus_path), str(output_path), str(state_path))

    assert first["summary"]["cached"] == 0
    assert second["summary"]["cached"] == 1
    assert generate.call_count == 1

    with patch("run_digest.generate_digest", return_value=digest) as generate:
        forced = run_corpus(
            str(corpus_path), str(output_path), str(state_path), force=True)
    assert forced["summary"]["cached"] == 0
    generate.assert_called_once()


def test_update_corpus_keeps_existing_cases_and_processed_ids(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    processed_path = tmp_path / "processed.json"
    existing = dict(CASE, id="old-article")
    new = dict(CASE, id="new-article")
    corpus_path.write_text(json.dumps([existing]), encoding="utf-8")
    processed_path.write_text(json.dumps(["old-article"]), encoding="utf-8")

    with patch("build_corpus.build_corpus", return_value=[new]) as build:
        cases, new_cases = update_corpus(
            str(corpus_path), str(processed_path), 20, with_attachments=True
        )

    build.assert_called_once_with(20, True, {"old-article"})
    assert [case["id"] for case in cases] == ["old-article", "new-article"]
    assert [case["id"] for case in new_cases] == ["new-article"]
    assert json.loads(processed_path.read_text(encoding="utf-8")) == [
        "new-article", "old-article"]


def test_ensure_corpus_builds_only_when_missing(tmp_path):
    from run_digest import ensure_corpus

    corpus_path = tmp_path / "missing.json"
    processed_path = tmp_path / "processed.json"

    def create_corpus(*args, **kwargs):
        corpus_path.write_text("[]", encoding="utf-8")

    with patch("build_corpus.update_corpus", side_effect=create_corpus) as update:
        assert ensure_corpus(str(corpus_path), str(processed_path), 7) is True
    update.assert_called_once_with(str(corpus_path), str(processed_path), 7, with_attachments=True)

    with patch("build_corpus.update_corpus") as update:
        assert ensure_corpus(str(corpus_path), str(processed_path), 7) is False
    update.assert_not_called()


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
    with patch("get_social_schools_news.generate_digest", side_effect=AssertionError):
        result = evaluate_product_case(record, [])

    assert result["id"] == "test-article"
    assert result["violations"] == []


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


def test_run_case_repeats_generation_for_extra_samples():
    """Sampling more than once is how a real difference is told from model luck"""
    digest = Digest("Test article", "Summary", [])
    with patch("run_digest.generate_digest", return_value=digest) as generate, \
            patch("run_digest.structural_violations", return_value=[]), \
            patch("run_digest.get_last_llm_usage", return_value={"cost_usd": 0.01, "requests": 1}):
        result = run_case(CASE, samples=3)

    assert generate.call_count == 3
    assert len(result["samples"]) == 3
    assert result["usage"]["cost_usd"] == pytest.approx(0.03)
    assert result["usage"]["requests"] == 3


def test_case_fingerprint_changes_with_the_model():
    """Switching models must never reuse another model's cached answers"""
    apply_llm_overrides(model="model-a")
    first = _case_fingerprint(CASE)
    apply_llm_overrides(model="model-b")
    second = _case_fingerprint(CASE)
    apply_llm_overrides(model="model-a")
    assert first != second
    assert _case_fingerprint(CASE) == first
    assert _case_fingerprint(CASE, samples=2) != first


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


def test_score_recall_uses_normalised_matching():
    digest = Digest("t", "Swimming at 08:30", [])
    hits, total, missing = score_recall(digest, ["8:30", "swimming"])
    assert (hits, total, missing) == (2, 2, [])


def test_find_unfaithful_claims_flags_invented_facts():
    """Recall alone rewards saying everything; this is what punishes inventing it"""
    digest = Digest("t", "Departure at 09:00", [])
    assert find_unfaithful_claims(digest, ["09:00"]) == [
        "states what the message does not: '09:00'"]
    assert find_unfaithful_claims(digest, ["10:00"]) == []


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


def test_parse_variant_splits_model_from_reasoning_effort():
    assert parse_variant("google/gemini-2.5-flash") == {
        "spec": "google/gemini-2.5-flash",
        "model": "google/gemini-2.5-flash",
        "reasoning": "",
    }
    assert parse_variant("google/gemini-2.5-pro@high")["reasoning"] == "high"
    # Ollama tags use a colon, so the effort separator must not be one.
    assert parse_variant("qwen2.5:7b")["model"] == "qwen2.5:7b"


def _summary(spec, passed, cost):
    split = {"cases": 4, "passed": passed, "pass_rate": passed / 4, "recall_hits": 0,
             "recall_total": 0, "recall": None, "violations": 0, "warnings": 0, "unstable": 0}
    return {"spec": spec, "usage": {"cost_usd": cost},
            "splits": {"all": split, "tune": split, "holdout": split}}


def test_format_verdict_calls_out_paying_more_for_nothing():
    verdict = format_verdict([_summary("cheap", 3, 0.01), _summary("pricey", 3, 0.10)])
    assert "not worth it" in verdict
    assert "10.0x the cost" in verdict

    better = format_verdict([_summary("cheap", 2, 0.01), _summary("pricey", 4, 0.05)])
    assert "+2 case(s)" in better
