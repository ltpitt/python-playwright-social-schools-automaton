import unittest
from unittest.mock import patch, mock_open, MagicMock
from io import BytesIO
from get_social_schools_news import (
    download_pdf_with_pycurl,
    extract_text_from_pdf,
    translate_text,
    send_pushbullet_notification,
)


class TestGetSocialSchoolsNews(unittest.TestCase):

    @patch("get_social_schools_news.pycurl.Curl")
    def test_download_pdf_with_pycurl(self, MockCurl):
        mock_curl_instance = MockCurl.return_value
        mock_curl_instance.setopt.side_effect = lambda option, value: (
            setattr(mock_curl_instance, "WRITEDATA", BytesIO(b"PDF content"))
            if option == mock_curl_instance.WRITEDATA
            else None
        )

        with patch("builtins.open", mock_open()) as mocked_file:
            download_pdf_with_pycurl("http://example.com/test.pdf", "test.pdf")
            mocked_file.assert_called_once_with("test.pdf", "wb")
            mocked_file().write.assert_called_once_with(b"PDF content")

    @patch("get_social_schools_news.fitz.open")
    def test_extract_text_from_pdf(self, mock_fitz_open):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page text"
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz_open.return_value = mock_doc

        text = extract_text_from_pdf("test.pdf")
        self.assertEqual(text, "Page text")

    @patch("get_social_schools_news.GoogleTranslator.translate")
    def test_translate_text(self, mock_translate):
        mock_translate.side_effect = lambda text: f"Translated {text}"
        text = "This is a test."
        translated_text = translate_text(text, src="en", dest="it")
        self.assertEqual(translated_text, "Translated This is a test.")

    @patch("get_social_schools_news.requests.post")
    def test_send_pushbullet_notification(self, MockPost):
        mock_response = MagicMock()
        mock_response.status_code = 200
        MockPost.return_value = mock_response

        send_pushbullet_notification("Test Title", "Test Body", "fake_api_key")
        MockPost.assert_called_once_with(
            "https://api.pushbullet.com/v2/pushes",
            data=unittest.mock.ANY,
            headers={
                "Authorization": "Bearer fake_api_key",
                "Content-Type": "application/json",
            },
        )


if __name__ == "__main__":
    unittest.main()
