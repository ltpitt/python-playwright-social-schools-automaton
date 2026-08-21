import json
from unittest.mock import patch

from get_social_schools_news import Digest, Topic
from build_corpus import update_corpus
from evaluate_digests import evaluate_product_case
from run_digest import run_case, run_corpus


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
    assert result["summary"] == {
        "total": 1, "cached": 0, "successful": 1, "failed": 0, "violations": 0}
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
