from unittest.mock import patch

from socialschools.state import load_processed_articles, save_processed_article


def test_load_processed_articles(tmp_path):
    path = str(tmp_path / 'processed.json')

    # Test empty file
    assert load_processed_articles(path) == []

    # Test with existing articles
    with open(path, 'w') as f:
        f.write('["article1", "article2"]')
    assert load_processed_articles(path) == ["article1", "article2"]


def test_save_processed_article(tmp_path):
    path = str(tmp_path / 'processed.json')

    # Test new article
    assert save_processed_article("article1", path) is True
    assert load_processed_articles(path) == ["article1"]

    # Test duplicate article
    assert save_processed_article("article1", path) is False


def test_load_processed_articles_error(tmp_path):
    path = str(tmp_path / 'processed.json')

    # Test invalid JSON file
    with open(path, 'w') as f:
        f.write('invalid json')
    assert load_processed_articles(path) == []


def test_save_processed_article_error(tmp_path):
    path = str(tmp_path / 'processed.json')

    # Test file permission error
    with patch('builtins.open', side_effect=PermissionError):
        assert save_processed_article("article1", path) is False
