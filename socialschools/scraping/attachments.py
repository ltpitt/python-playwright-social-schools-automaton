"""Fetching an Article's attachments and turning them into text.

Downloads go through the authenticated Playwright context (ADR 0003): these
files sit behind the same login as the post, so an anonymous fetch gets a login
page rendered as a PDF rather than the newsletter.

One failed attachment must never lose the Article. A failure is recorded as a
failed Attachment, which reaches the parent as a "could not be read" warning and
the admin as an alert.
"""
import logging
import os
import tempfile

import fitz  # PyMuPDF
import requests
from docx import Document

from ..delivery.admin import notify_admin
from ..models import Attachment

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 8192


def download_attachment(url, output_path, browser_context=None):
    """Save a URL to disk, using the authenticated session when there is one."""
    if browser_context is not None:
        logger.info(f"Downloading {url} (authenticated session)")
        resp = browser_context.request.get(url)
        if not resp.ok:
            raise IOError(f"Authenticated download failed ({resp.status}): {url}")
        with open(output_path, "wb") as f:
            f.write(resp.body())
    else:
        logger.info(f"Downloading {url}")
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
    logger.info(f"Downloaded to {output_path}")


def extract_pdf_text(pdf_path):
    logger.info(f"Extracting text from PDF {pdf_path}")
    doc = fitz.open(pdf_path)
    try:
        text = "".join(page.get_text() for page in doc)
        logger.info(f"Text extraction complete for {pdf_path}")
        return text
    finally:
        doc.close()


def extract_docx_text(docx_path):
    logger.info(f"Extracting text from Word document {docx_path}")
    doc = Document(docx_path)
    text = "".join(paragraph.text + "\n" for paragraph in doc.paragraphs)
    logger.info(f"Text extraction complete for {docx_path}")
    return text


_EXTRACTORS = {"pdf": extract_pdf_text, "docx": extract_docx_text}


def _filename_from(url):
    return url.split("/")[-1].split("?")[0]


def process_links(context, links, filetype):
    """Download and extract every link, one Attachment each, failures included."""
    extract = _EXTRACTORS[filetype]
    attachments = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for link in links:
            url = link.get_attribute("href")
            filename = _filename_from(url)
            path = os.path.join(temp_dir, filename)
            try:
                download_attachment(url, path, browser_context=context)
                text = extract(path)
                attachments.append(
                    Attachment(filename=filename, url=url, filetype=filetype, text=text))
            except Exception as e:
                logger.error(f"Failed to process {filetype.upper()} '{filename}': {e}")
                notify_admin("Attachment could not be processed",
                             f"{filetype.upper()}: {filename}\nURL: {url}", exc=e)
                attachments.append(
                    Attachment(filename=filename, url=url, filetype=filetype,
                               text="", failed=True))
    return attachments


def collect_attachments(article, context):
    """Every PDF and Word attachment linked from an Article, as text."""
    all_links = article.query_selector_all("a[href]")
    if all_links:
        hrefs = [link.get_attribute("href") for link in all_links if link.get_attribute("href")]
        if hrefs:
            logger.debug(f"Article links ({len(hrefs)}): {[h.split('?')[0] for h in hrefs]}")

    pdf_links = article.query_selector_all("a[href*='.pdf']")
    docx_links = article.query_selector_all("a[href*='.docx']")
    if not pdf_links and not docx_links:
        logger.info("No PDFs or Word documents found in article.")

    attachments = []
    if pdf_links:
        attachments.extend(process_links(context, pdf_links, "pdf"))
    if docx_links:
        attachments.extend(process_links(context, docx_links, "docx"))
    return pdf_links, docx_links, attachments
