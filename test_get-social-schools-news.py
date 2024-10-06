import unittest
from unittest.mock import patch, mock_open, MagicMock
import os
from io import BytesIO
from get-social-schools-news import (
    download_pdf_with_pycurl,
    extract_text_from_pdf,
    translate_text,
    send_pushbullet_notification,
)

class TestGetSocialSchoolsNews(unittest.TestCase):

    @patch("get-social-schools-news.pycurl.Curl")
    def test_download_pdf_with_pycurl(self, MockCurl):
        mock_curl_instance = MockCurl.return_value
        mock_curl_instance.perform.return_value = None
        buffer = BytesIO(b"PDF content")
        mock_curl_instance.WRITEDATA = buffer

        with patch("builtins.open", mock_open()) as mocked_file:
            download_pdf_with_pycurl("http://example.com/test.pdf", "test.pdf")
            mocked_file.assert_called_once_with("test.pdf", "wb")
            mocked_file().write.assert_called_once_with(b"PDF content")

    @patch("get-social-schools-news.fitz.open")
    def test_extract_text_from_pdf(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page text"
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz_open.return_value = mock_doc

        text = extract_text_from_pdf("test.pdf")
        self.assertEqual(text, "Page text")

    @patch("get-social-schools-news.GoogleTranslator.translate")
    def test_translate_text(self, mock_translate):
        mock_translate.side_effect = lambda text: f"Translated {text}"
        text = "This is a test."
        translated_text = translate_text(text, src="en", dest="it")
        self.assertEqual(translated_text, "Translated This is a test.")

    @patch("get-social-schools-news.Pushbullet")
    def test_send_pushbullet_notification(self, MockPushbullet):
        mock_pb_instance = MockPushbullet.return_value
        send_pushbullet_notification("Test Title", "Test Body", "fake_api_key")
        mock_pb_instance.push_note.assert_called_once_with("Test Title", "Test Body")

if __name__ == "__main__":
    unittest.main()
