import json
import random
from unittest.mock import patch

from socialschools.models import Quote
from socialschools.quotes import LIGHT_TONE_EMOJI, draw_quote, load_quotes, quote_line


def _write_csv(path, rows):
    header = "id,quote,language,tone\n"
    path.write_text(header + "".join(rows), encoding="utf-8")
    return str(path)


def _quotes(count):
    return [Quote(id=str(n), text=f"Quote {n}", language="en", tone="reflective", emoji="")
            for n in range(count)]


def _draw_many(quotes, state, count, seed=1):
    rng = random.Random(seed)
    return [draw_quote(quotes, state_path=state, rng=rng).id for _ in range(count)]


# =============================================================================
# LOADING THE CSV
# =============================================================================


def test_load_quotes_without_a_file_is_empty(tmp_path):
    assert load_quotes(str(tmp_path / "missing.csv")) == []


def test_load_quotes_reads_the_columns(tmp_path):
    path = _write_csv(tmp_path / "q.csv", ['7,"Be kind, always.",en,reflective\n'])
    [quote] = load_quotes(path)
    assert (quote.id, quote.text, quote.language, quote.tone) == (
        "7", "Be kind, always.", "en", "reflective")


def test_load_quotes_skips_rows_without_an_id_or_text(tmp_path):
    path = _write_csv(tmp_path / "q.csv", [
        '1,"Fine",en,reflective\n',
        ',"No id",en,reflective\n',
        '3,,en,reflective\n',
    ])
    assert [q.id for q in load_quotes(path)] == ["1"]


def test_load_quotes_keeps_the_first_of_a_duplicated_id(tmp_path):
    path = _write_csv(tmp_path / "q.csv", [
        '1,"First",en,reflective\n',
        '1,"Second",en,reflective\n',
    ])
    assert [q.text for q in load_quotes(path)] == ["First"]


def test_a_light_quote_gets_an_emoji_and_a_serious_one_does_not(tmp_path):
    path = _write_csv(tmp_path / "q.csv", [
        '1,"Funny",en,humorous\n',
        '2,"Serious",en,inspirational\n',
    ])
    funny, serious = load_quotes(path)
    assert funny.emoji in LIGHT_TONE_EMOJI
    assert serious.emoji == ""


def test_the_emoji_for_a_quote_is_stable_between_loads(tmp_path):
    path = _write_csv(tmp_path / "q.csv", ['1,"Funny",en,humorous\n'])
    assert load_quotes(path)[0].emoji == load_quotes(path)[0].emoji


def test_an_emoji_column_overrides_the_tone_default(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text('id,quote,language,tone,emoji\n1,"Funny",en,humorous,\U0001F9E6\n'
                    '2,"Serious",en,inspirational,\U0001F31F\n', encoding="utf-8")
    funny, serious = load_quotes(str(path))
    assert funny.emoji == "\U0001F9E6"
    assert serious.emoji == "\U0001F31F"


# =============================================================================
# ROTATING THROUGH THEM
# =============================================================================


def test_no_quotes_means_no_draw_and_no_state(tmp_path):
    state = tmp_path / "deck.json"
    assert draw_quote([], state_path=str(state)) is None
    assert not state.exists()


def test_every_quote_is_used_once_before_any_is_repeated(tmp_path):
    state = str(tmp_path / "deck.json")
    drawn = _draw_many(_quotes(10), state, 10)
    assert sorted(drawn) == sorted(q.id for q in _quotes(10))


def test_a_repeat_is_always_at_least_half_the_catalogue_away(tmp_path):
    state = str(tmp_path / "deck.json")
    size = 10
    drawn = _draw_many(_quotes(size), state, size * 6, seed=7)
    last_seen = {}
    for position, quote_id in enumerate(drawn):
        if quote_id in last_seen:
            assert position - last_seen[quote_id] >= size // 2
        last_seen[quote_id] = position


def test_the_rotation_survives_a_restart(tmp_path):
    state = str(tmp_path / "deck.json")
    quotes = _quotes(6)
    first = [draw_quote(quotes, state_path=state, rng=random.Random(n)).id for n in range(3)]
    second = [draw_quote(quotes, state_path=state, rng=random.Random(n + 10)).id for n in range(3)]
    assert sorted(first + second) == sorted(q.id for q in quotes)


def test_a_quote_added_mid_cycle_is_used_before_the_cycle_ends(tmp_path):
    state = str(tmp_path / "deck.json")
    quotes = _quotes(5)
    drawn = _draw_many(quotes, state, 2)
    quotes.append(Quote(id="new", text="New", language="en", tone="reflective", emoji=""))
    drawn += _draw_many(quotes, state, 4, seed=3)
    assert "new" in drawn


def test_a_quote_removed_from_the_file_is_never_drawn_again(tmp_path):
    state = str(tmp_path / "deck.json")
    quotes = _quotes(5)
    _draw_many(quotes, state, 2)
    remaining = [q for q in quotes if q.id != "3"]
    assert "3" not in _draw_many(remaining, state, 12, seed=5)


def test_a_corrupt_state_file_is_rebuilt_not_fatal(tmp_path):
    state = tmp_path / "deck.json"
    state.write_text("not json", encoding="utf-8")
    assert draw_quote(_quotes(3), state_path=str(state)) is not None
    assert json.loads(state.read_text(encoding="utf-8"))["remaining"] is not None


def test_a_state_file_that_cannot_be_written_still_yields_a_quote(tmp_path):
    with patch("socialschools.quotes.paths.ensure_parent", side_effect=OSError("read-only")):
        assert draw_quote(_quotes(3), state_path=str(tmp_path / "deck.json")) is not None


# =============================================================================
# THE LINE A PARENT READS
# =============================================================================


def test_quote_line_appends_the_emoji():
    quote = Quote(id="1", text="Funny", language="en", tone="humorous", emoji="\U0001F605")
    assert quote_line(quote, "en") == "Funny \U0001F605"


def test_quote_line_has_no_trailing_space_without_an_emoji():
    quote = Quote(id="1", text="Serious", language="en", tone="inspirational", emoji="")
    assert quote_line(quote, "en") == "Serious"


def test_quote_line_translates_into_the_readers_language():
    quote = Quote(id="1", text="Serious", language="en", tone="inspirational", emoji="")
    with patch("socialschools.quotes.translate", return_value="Serio") as mock_translate:
        assert quote_line(quote, "nl") == "Serio"
    mock_translate.assert_called_once_with("Serious", src="en", dest="nl")


def test_quote_line_does_not_translate_a_quote_already_in_that_language():
    quote = Quote(id="1", text="Serious", language="en", tone="inspirational", emoji="")
    with patch("socialschools.quotes.translate") as mock_translate:
        quote_line(quote, "en")
    mock_translate.assert_not_called()


def test_quote_line_falls_back_to_the_original_when_translation_fails():
    quote = Quote(id="1", text="Serious", language="en", tone="inspirational", emoji="")
    with patch("socialschools.quotes.translate", side_effect=RuntimeError("offline")):
        assert quote_line(quote, "nl") == "Serious"
