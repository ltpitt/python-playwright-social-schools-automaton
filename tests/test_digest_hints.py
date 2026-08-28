import pytest

from socialschools.digest.hints import extract_action_hints


@pytest.mark.parametrize("text", [
    "Graag meenemen op maandag.",
    "Graag voor vrijdag doorgeven aan de leerkracht.",
    "Wilt u uw kind uiterlijk 29 mei aanmelden.",
    "Zorg dat je kind op tijd is.",
    "Vergeet niet de gymtas mee te geven.",
])
def test_a_real_request_is_still_found(text):
    assert any(h.startswith("instruction:") for h in extract_action_hints(text))


@pytest.mark.parametrize("text", [
    "In mijn vrije tijd lees ik graag.",
    "Ik lees graag en wandel graag.",
    "Ik zou graag een kat hebben.",
    "Zij werkt graag met kinderen.",
])
def test_a_preference_is_not_a_request(text):
    """'graag' is both 'please' and 'gladly', and a teacher interview is full of the second.

    A bare match handed the model obligations invented out of small talk.
    """
    assert [h for h in extract_action_hints(text) if h.startswith("instruction:")] == []


def test_extract_action_hints_finds_dutch_date():
    hints = extract_action_hints("Lever het formulier in voor 15 aug alstublieft.")
    assert any("15 aug" in h for h in hints)


def test_extract_action_hints_finds_time():
    hints = extract_action_hints("De school start om 08:30 uur.")
    assert any(h == "time: 08:30" for h in hints)


def test_extract_action_hints_finds_imperative_phrase():
    hints = extract_action_hints("Gelieve het formulier voor vrijdag in te leveren.")
    assert any(h.startswith("instruction:") for h in hints)


def test_extract_action_hints_empty_when_no_matches():
    assert extract_action_hints("Fijne dag allemaal, tot morgen.") == []
