import json
from unittest.mock import patch

from tools.build_corpus import update_corpus

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


def test_update_corpus_keeps_existing_cases_and_processed_ids(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    processed_path = tmp_path / "processed.json"
    existing = dict(CASE, id="old-article")
    new = dict(CASE, id="new-article")
    corpus_path.write_text(json.dumps([existing]), encoding="utf-8")
    processed_path.write_text(json.dumps(["old-article"]), encoding="utf-8")

    with patch("tools.build_corpus.build_corpus", return_value=[new]) as build:
        cases, new_cases = update_corpus(
            str(corpus_path), str(processed_path), 20, with_attachments=True
        )

    build.assert_called_once_with(20, True, {"old-article"})
    assert [case["id"] for case in cases] == ["old-article", "new-article"]
    assert [case["id"] for case in new_cases] == ["new-article"]
    assert json.loads(processed_path.read_text(encoding="utf-8")) == [
        "new-article", "old-article"]
