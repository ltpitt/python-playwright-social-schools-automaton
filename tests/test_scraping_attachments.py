from unittest.mock import Mock, patch

from socialschools.models import Attachment
from socialschools.scraping.attachments import (
    extract_docx_text,
    extract_pdf_text,
    process_links,
)


def test_extract_text_from_pdf():
    """Test text extraction from PDF"""
    mock_text = "Extracted PDF text content"

    with patch('fitz.open') as mock_fitz_open:
        mock_doc = Mock()
        mock_page = Mock()
        mock_page.get_text.return_value = mock_text
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))
        mock_fitz_open.return_value = mock_doc

        result = extract_pdf_text("/tmp/test.pdf")

        assert result == mock_text
        mock_fitz_open.assert_called_once_with("/tmp/test.pdf")
        mock_page.get_text.assert_called_once()
        mock_doc.close.assert_called_once()


def test_process_pdf_links():
    """Test processing PDF links returns Attachment objects with no failures"""
    context = Mock()

    # Mock PDF links
    mock_link1 = Mock()
    mock_link1.get_attribute.return_value = "http://example.com/test1.pdf"
    mock_link2 = Mock()
    mock_link2.get_attribute.return_value = "http://example.com/test2.pdf"
    pdf_links = [mock_link1, mock_link2]

    mock_extract = Mock(return_value="PDF content")
    with patch('socialschools.scraping.attachments.download_attachment') as mock_download, \
         patch.dict('socialschools.scraping.attachments._EXTRACTORS', {"pdf": mock_extract}), \
         patch('tempfile.TemporaryDirectory'):

        attachments = process_links(context, pdf_links, "pdf")

        assert mock_download.call_count == 2
        assert mock_extract.call_count == 2
        assert all(isinstance(a, Attachment) for a in attachments)
        assert [a.filename for a in attachments] == ["test1.pdf", "test2.pdf"]
        assert all(a.text == "PDF content" for a in attachments)
        assert all(not a.failed for a in attachments)


def test_process_pdf_links_partial_failure():
    """Test that a failing PDF is recorded with failed=True without stopping other attachments"""
    context = Mock()

    mock_link1 = Mock()
    mock_link1.get_attribute.return_value = "http://example.com/ok.pdf"
    mock_link2 = Mock()
    mock_link2.get_attribute.return_value = "http://example.com/broken.pdf"
    pdf_links = [mock_link1, mock_link2]

    def download_side_effect(url, path, browser_context=None):
        if "broken" in url:
            raise Exception("404 Not Found")

    with patch('socialschools.scraping.attachments.download_attachment',
               side_effect=download_side_effect), \
         patch.dict('socialschools.scraping.attachments._EXTRACTORS',
                    {"pdf": Mock(return_value="OK content")}), \
         patch('tempfile.TemporaryDirectory'):
        attachments = process_links(context, pdf_links, "pdf")

    assert len(attachments) == 2
    ok, broken = attachments
    assert ok.filename == "ok.pdf" and not ok.failed and ok.text == "OK content"
    assert broken.filename == "broken.pdf" and broken.failed


def test_extract_text_from_docx():
    """Test text extraction from Word document"""
    with patch('socialschools.scraping.attachments.Document') as mock_document:
        mock_doc = Mock()
        mock_paragraph1 = Mock()
        mock_paragraph1.text = "First paragraph"
        mock_paragraph2 = Mock()
        mock_paragraph2.text = "Second paragraph"
        mock_doc.paragraphs = [mock_paragraph1, mock_paragraph2]
        mock_document.return_value = mock_doc

        result = extract_docx_text("/tmp/test.docx")

        expected = "First paragraph\nSecond paragraph\n"
        assert result == expected
        mock_document.assert_called_once_with("/tmp/test.docx")


def test_process_docx_links():
    """Test processing DOCX links returns Attachment objects"""
    context = Mock()

    # Mock DOCX link
    mock_link = Mock()
    mock_link.get_attribute.return_value = "http://example.com/test.docx"
    docx_links = [mock_link]

    mock_extract = Mock(return_value="DOCX content")
    with patch('socialschools.scraping.attachments.download_attachment') as mock_download, \
         patch.dict('socialschools.scraping.attachments._EXTRACTORS', {"docx": mock_extract}), \
         patch('tempfile.TemporaryDirectory'):

        attachments = process_links(context, docx_links, "docx")

        mock_download.assert_called_once()
        mock_extract.assert_called_once()
        assert len(attachments) == 1
        assert isinstance(attachments[0], Attachment)
        assert attachments[0].filename == "test.docx"
        assert attachments[0].text == "DOCX content"
        assert not attachments[0].failed
