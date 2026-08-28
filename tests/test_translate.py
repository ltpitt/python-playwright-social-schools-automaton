from unittest.mock import Mock, patch

import pytest

from socialschools.translate import translate


def test_translate(mock_config):
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.return_value = "Translated text"
        result = translate("Original text")
        assert result == "Translated text"
        mock_translate.assert_called_once()


def test_translate_caches_identical_text_and_language(mock_config):
    """Repeated translate() calls for the same text+language reuse the cached result"""
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.return_value = "Vertaald"
        first = translate("Original text", dest="nl")
        second = translate("Original text", dest="nl")
        assert first == second == "Vertaald"
        mock_translate.assert_called_once()


def test_translate_does_not_reuse_cache_across_languages(mock_config):
    """The same text translated into a different language triggers a fresh call"""
    with patch('deep_translator.GoogleTranslator.translate') as mock_translate:
        mock_translate.side_effect = ["Vertaald", "Translated"]
        translate("Original text", dest="nl")
        translate("Original text", dest="en")
        assert mock_translate.call_count == 2


def test_translate_error(mock_config):
    translate_side_effect = Exception("Translation failed")
    with patch('deep_translator.GoogleTranslator.translate',
               side_effect=translate_side_effect):
        with pytest.raises(Exception):
            translate("Original text")


@pytest.mark.parametrize("language,expected", [
    ("nl", "en"),  # Default destination
    ("en", "it"),  # Custom destination
    ("fr", "es"),  # Different source and destination
])
def test_translate_with_different_languages(mock_config, language, expected):
    """Test translation with different source and destination languages"""
    with patch('socialschools.translate.GoogleTranslator') as mock_translator_class:
        mock_translator = Mock()
        mock_translator.translate.return_value = f"translated to {expected}"
        mock_translator_class.return_value = mock_translator

        result = translate("test text", src=language, dest=expected)

        mock_translator_class.assert_called_once_with(source=language,
                                                      target=expected)
        assert result == f"translated to {expected}"


def test_translate_with_chunks(mock_config):
    """Test translation with text that requires chunking"""
    long_text = "a" * 10000  # Text longer than default chunk size

    with patch('socialschools.translate.GoogleTranslator') as mock_translator_class:
        mock_translator = Mock()
        mock_translator.translate.side_effect = lambda chunk: f"t({len(chunk)})"
        mock_translator_class.return_value = mock_translator

        result = translate(long_text, chunk_size=4900)

        # Should be called 3 times for the chunks
        assert mock_translator.translate.call_count == 3
        assert result == "t(4900) t(4900) t(200)"
