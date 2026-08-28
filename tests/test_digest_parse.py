import pytest

from socialschools.digest.parse import dict_to_digest


def test_dict_to_digest_accepts_undated_entries():
    """An entry with no date prefix is valid content, not a schema violation"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{
            "heading": "School supplies",
            "actions": ["Provide the listed school supplies"],
            "bring": ["12 colouring pencils", "headphones"],
            "notes": [],
        }],
    }
    digest = dict_to_digest(data)
    assert digest.topics[0].bring == ["12 colouring pencils", "headphones"]


def test_dict_to_digest_drops_topics_with_no_entries():
    """A heading with nothing under it is noise and must not reach the reader"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [
            {"heading": "Empty", "actions": [], "bring": [], "notes": []},
            {"heading": "Real", "actions": ["Do the thing"], "bring": [], "notes": []},
        ],
    }
    digest = dict_to_digest(data)
    assert [t.heading for t in digest.topics] == ["Real"]


def test_dict_to_digest_defaults_missing_entry_lists():
    """A topic may omit lists it has nothing for"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [{"heading": "Trip", "actions": ["Pack a bag"]}],
    }
    digest = dict_to_digest(data)
    assert digest.topics[0].bring == []
    assert digest.topics[0].notes == []


def test_dict_to_digest_rejects_non_object_topic():
    data = {"translated_title": "Test", "tldr": "Summary", "topics": ["not an object"]}
    with pytest.raises(ValueError, match="must be an object"):
        dict_to_digest(data)


def test_dict_to_digest_deduplicates_entries_within_a_topic():
    """Test that duplicate entries are removed preserving insertion order"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{
            "heading": "Trip",
            "actions": ["15 Aug - sign form", "15 Aug - sign form", "25 Aug - attend"],
            "bring": ["towel", "towel"],
            "notes": ["4 Jul - holiday", "4 Jul - holiday"],
        }],
    }
    digest = dict_to_digest(data)
    topic = digest.topics[0]
    assert topic.actions == ["15 Aug - sign form", "25 Aug - attend"]
    assert topic.bring == ["towel"]
    assert topic.notes == ["4 Jul - holiday"]


def test_dict_to_digest_rejects_empty_digest():
    """Test that a digest with no tldr and no topic content is rejected as content-less"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [],
    }
    with pytest.raises(ValueError, match="no content"):
        dict_to_digest(data)


def test_dict_to_digest_accepts_tldr_only_digest():
    """Test that a non-empty tldr alone is sufficient content, even with no topics"""
    data = {
        "translated_title": "Test",
        "tldr": "Nothing to do this week.",
        "topics": [],
    }
    digest = dict_to_digest(data)
    assert digest.tldr == "Nothing to do this week."


def test_dict_to_digest_rejects_non_string_action():
    """Test that a non-string entry in a topic's actions is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "",
        "topics": [{"heading": "T", "actions": [{"text": "15 Aug - sign form"}],
                    "bring": [], "notes": []}],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        dict_to_digest(data)


def test_dict_to_digest_rejects_blank_note():
    """Test that a blank/whitespace-only entry is rejected"""
    data = {
        "translated_title": "Test",
        "tldr": "Summary",
        "topics": [{"heading": "T", "actions": [], "bring": [], "notes": ["   "]}],
    }
    with pytest.raises(ValueError, match="non-empty strings"):
        dict_to_digest(data)
