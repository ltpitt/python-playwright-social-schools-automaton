from datetime import date
from unittest.mock import Mock

import pytest

from socialschools.scraping.feed import expand_full_text, get_post_date


def _mock_article_with_date_text(text):
    article = Mock()
    date_el = Mock()
    date_el.inner_text.return_value = text
    article.query_selector.return_value = date_el
    return article


def test_get_post_date_valid_with_time():
    """Test that real Social Schools text ('D month om HH:MM') keeps both date and time"""
    article = _mock_article_with_date_text("7 juli om 13:19")
    assert get_post_date(article) == "7 Jul 13:19"


def test_get_post_date_valid_without_time():
    """Test that a date with no time suffix still parses to just 'D Mon'"""
    article = _mock_article_with_date_text("1 juli")
    assert get_post_date(article) == "1 Jul"


@pytest.mark.parametrize("dutch,expected_abbr", [
    ("januari", "Jan"), ("februari", "Feb"), ("maart", "Mar"), ("april", "Apr"),
    ("mei", "May"), ("juni", "Jun"), ("juli", "Jul"), ("augustus", "Aug"),
    ("september", "Sep"), ("oktober", "Oct"), ("november", "Nov"), ("december", "Dec"),
])
def test_get_post_date_all_dutch_months(dutch, expected_abbr):
    """Test that every Dutch month name maps to the correct English abbreviation"""
    article = _mock_article_with_date_text(f"23 {dutch} om 09:05")
    assert get_post_date(article) == f"23 {expected_abbr} 09:05"


def test_get_post_date_case_insensitive():
    """Test that month names are matched regardless of case"""
    article = _mock_article_with_date_text("3 JULI om 14:09")
    assert get_post_date(article) == "3 Jul 14:09"


def test_get_post_date_single_digit_day():
    """Test that a single-digit day is not zero-padded"""
    article = _mock_article_with_date_text("3 juli om 14:09")
    assert get_post_date(article) == "3 Jul 14:09"


def test_get_post_date_no_date_element():
    """Test that a missing date link (no a.meta-info) returns None"""
    article = Mock()
    article.query_selector.return_value = None
    assert get_post_date(article) is None


def test_get_post_date_empty_text():
    """Test that an empty date text returns None"""
    article = _mock_article_with_date_text("")
    assert get_post_date(article) is None


def test_get_post_date_unparseable_text():
    """Test that text without a recognizable day/month returns None instead of raising"""
    article = _mock_article_with_date_text("not-a-date")
    assert get_post_date(article) is None


def test_get_post_date_ignores_edited_suffix():
    """An edited post appends ', bijgewerkt ...'; the original posting time must win"""
    article = _mock_article_with_date_text("7 juli om 13:19,\xa0bijgewerkt\xa07 juli om 16:47")
    assert get_post_date(article) == "7 Jul 13:19"


@pytest.mark.parametrize("word,expected_day", [
    ("vandaag", 21), ("gisteren", 20), ("eergisteren", 19),
])
def test_get_post_date_resolves_relative_day(word, expected_day):
    """Recent posts are labelled 'vandaag'/'gisteren' and must resolve to a real date"""
    article = _mock_article_with_date_text(f"{word} om 15:47,\xa0bijgewerkt\xa0{word} om 16:47")
    assert get_post_date(article, today=date(2026, 8, 21)) == f"{expected_day} Aug 15:47"


def test_get_post_date_resolves_past_weekday():
    """'afgelopen dinsdag' resolves to the most recent past Tuesday"""
    article = _mock_article_with_date_text("afgelopen dinsdag om 15:39")
    # 2026-08-21 is a Friday, so the preceding Tuesday is the 18th.
    assert get_post_date(article, today=date(2026, 8, 21)) == "18 Aug 15:39"


def test_get_post_date_weekday_matching_today_resolves_to_last_week():
    """A weekday label never means today, so it resolves a full week back"""
    article = _mock_article_with_date_text("afgelopen vrijdag om 09:00")
    assert get_post_date(article, today=date(2026, 8, 21)) == "14 Aug 09:00"


def test_get_post_date_relative_without_time():
    """A relative label with no time still yields a date"""
    article = _mock_article_with_date_text("gisteren")
    assert get_post_date(article, today=date(2026, 8, 21)) == "20 Aug"


def test_expand_full_text_with_button():
    """Test expanding full text when 'Meer weergeven' button exists"""
    article = Mock()
    more_button = Mock()
    article.query_selector.return_value = more_button

    expand_full_text(article)

    article.query_selector.assert_called_once_with(
        "button:has-text('Meer weergeven')"
    )
    more_button.click.assert_called_once()
    article.wait_for_selector.assert_any_call("span[as='div']", timeout=10000)


def test_expand_full_text_no_button():
    """Test expanding full text when no 'Meer weergeven' button exists"""
    article = Mock()
    article.query_selector.return_value = None

    expand_full_text(article)

    article.query_selector.assert_called_once()
    article.wait_for_selector.assert_any_call("span[as='div']", timeout=10000)


def test_expand_full_text_timeout_is_non_fatal():
    """A missing or delayed full-text block must not abort the whole run."""
    article = Mock()
    article.query_selector.return_value = None
    article.wait_for_selector.side_effect = [TimeoutError("missing full-text block"), None]

    expand_full_text(article)

    article.query_selector.assert_called_once_with("button:has-text('Meer weergeven')")
    assert article.wait_for_selector.call_args_list[0].args == ("span[as='div']",)
    assert article.wait_for_selector.call_args_list[0].kwargs == {"timeout": 10000}
    assert article.wait_for_selector.call_count == 2
