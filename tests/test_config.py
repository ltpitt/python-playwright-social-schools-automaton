from unittest.mock import Mock, patch

from socialschools import paths
from socialschools.config import Config, get_config, load_config, reset_config


def test_load_config_with_config_ini(tmp_path):
    """Test load_config with config.ini file"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: {
                'PUSHBULLET_API_KEYS': 'Test:api_key_123',
                'TRANSLATION_LANGUAGE': 'it',
            }.get(key, default))

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.SCRAPED_WEBSITE_USER == 'user@example.com'
        assert result.SCRAPED_WEBSITE_PASSWORD == 'password123'
        assert result.PUSHBULLET_API_KEYS == 'Test:api_key_123'
        assert result.TRANSLATION_LANGUAGE == 'it'


def test_load_config_fallback_to_example(tmp_path):
    """Test load_config falls back to config.example.ini"""
    with patch('os.path.exists', return_value=False):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'example@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'example_pass',
            'PUSHBULLET_API_KEYS': 'Test:example_key'
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: {'TRANSLATION_LANGUAGE': 'en'}.get(key, default))

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.SCRAPED_WEBSITE_USER == 'example@example.com'
        assert result.TRANSLATION_LANGUAGE == 'en'


def test_get_config_caching():
    """Test that get_config caches the configuration"""
    cached = Config(
        SCRAPED_WEBSITE_USER="cached@example.com",
        SCRAPED_WEBSITE_PASSWORD="cached_pass",
        PUSHBULLET_API_KEYS="Test:cached_key",
    )
    with patch('socialschools.config.load_config', return_value=cached) as mock_load:
        reset_config()

        # First call should load config
        result1 = get_config()
        assert mock_load.call_count == 1

        # Second call should use cached config
        result2 = get_config()
        assert mock_load.call_count == 1  # No additional calls
        assert result1 is result2
    reset_config()


def test_load_config_reads_reasoning_and_structured_output(tmp_path):
    """The two knobs a bakeoff varies must be readable from config"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: {
                'LLM_REASONING_EFFORT': 'Medium',
                'LLM_STRUCTURED_OUTPUT': 'false',
            }.get(key, default))

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

    assert result.LLM_REASONING_EFFORT == 'medium'
    assert result.LLM_STRUCTURED_OUTPUT is False


def test_config_missing_translation_language():
    """Test config loading with missing TRANSLATION_LANGUAGE"""
    with patch('os.path.exists', return_value=True):
        mock_default_section = Mock()
        mock_default_section.__getitem__ = Mock(side_effect=lambda key: {
            'SCRAPED_WEBSITE_USER': 'user@example.com',
            'SCRAPED_WEBSITE_PASSWORD': 'password123',
            'PUSHBULLET_API_KEYS': 'Test:api_key_123'
        }[key])
        mock_default_section.get = Mock(
            side_effect=lambda key, default=None: default)

        mock_parser = Mock()
        mock_parser.__getitem__ = Mock(return_value=mock_default_section)

        with patch('configparser.ConfigParser') as mock_config_parser:
            mock_config_parser.return_value = mock_parser
            result = load_config()

        assert result.TRANSLATION_LANGUAGE == 'en'


def test_load_config_reads_admin_settings(tmp_path):
    config_file = tmp_path / "config.ini"
    config_file.write_text(
        "[DEFAULT]\n"
        "SCRAPED_WEBSITE_USER = u\n"
        "SCRAPED_WEBSITE_PASSWORD = p\n"
        "ADMIN_PUSHBULLET_API_KEY = o.admin\n"
        "ADMIN_EMAIL = admin@example.com\n"
    )
    with patch.object(paths, "CONFIG_FILE", str(config_file)):
        result = load_config()

    assert result.ADMIN_PUSHBULLET_API_KEY == "o.admin"
    assert result.ADMIN_EMAIL == "admin@example.com"
