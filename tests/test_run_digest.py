import json
from unittest.mock import patch

import pytest

from socialschools.models import Digest, Topic
from tools.run_digest import _case_fingerprint, apply_llm_overrides, run_case, run_corpus

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
    with patch("tools.run_digest.generate_digest", return_value=digest), \
            patch("tools.run_digest.structural_violations", return_value=[]):
        result = run_case(CASE)

    assert result["source"] == CASE
    assert result["product"]["digest"]["tldr"] == "Bring a hat."
    assert "Bring: a hat" in result["product"]["notification"]
    assert result["error"] is None


def test_run_case_records_generation_failure():
    with patch("tools.run_digest.generate_digest", side_effect=RuntimeError("model down")):
        result = run_case(CASE)

    assert result["product"] is None
    assert result["error"] == "RuntimeError: model down"
    assert result["violations"] == ["digest failed: model down"]


def test_run_corpus_writes_json_product(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    output_path = tmp_path / "product.json"
    corpus_path.write_text(json.dumps([CASE]), encoding="utf-8")
    digest = Digest("Test article", "Summary", [])

    with patch("tools.run_digest.generate_digest", return_value=digest), \
            patch("tools.run_digest.structural_violations", return_value=[]):
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

    with patch("tools.run_digest.generate_digest", return_value=digest) as generate:
        first = run_corpus(str(corpus_path), str(output_path), str(state_path))
        second = run_corpus(str(corpus_path), str(output_path), str(state_path))

    assert first["summary"]["cached"] == 0
    assert second["summary"]["cached"] == 1
    assert generate.call_count == 1

    with patch("tools.run_digest.generate_digest", return_value=digest) as generate:
        forced = run_corpus(
            str(corpus_path), str(output_path), str(state_path), force=True)
    assert forced["summary"]["cached"] == 0
    generate.assert_called_once()


def test_ensure_corpus_builds_only_when_missing(tmp_path):
    from tools.run_digest import ensure_corpus

    corpus_path = tmp_path / "missing.json"
    processed_path = tmp_path / "processed.json"

    def create_corpus(*args, **kwargs):
        corpus_path.write_text("[]", encoding="utf-8")

    with patch("tools.build_corpus.update_corpus", side_effect=create_corpus) as update:
        assert ensure_corpus(str(corpus_path), str(processed_path), 7) is True
    update.assert_called_once_with(str(corpus_path), str(processed_path), 7, with_attachments=True)

    with patch("tools.build_corpus.update_corpus") as update:
        assert ensure_corpus(str(corpus_path), str(processed_path), 7) is False
    update.assert_not_called()


def test_run_case_repeats_generation_for_extra_samples():
    """Sampling more than once is how a real difference is told from model luck"""
    digest = Digest("Test article", "Summary", [])
    with patch("tools.run_digest.generate_digest", return_value=digest) as generate, \
            patch("tools.run_digest.structural_violations", return_value=[]), \
            patch("tools.run_digest.get_last_llm_usage",
                  return_value={"cost_usd": 0.01, "requests": 1}):
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
