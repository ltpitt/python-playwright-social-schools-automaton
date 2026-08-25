from socialschools.digest.hints import extract_action_hints


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
