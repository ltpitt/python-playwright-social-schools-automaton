import os
import pycurl
import logging
import traceback
from io import BytesIO
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import fitz  # PyMuPDF
import requests
from deep_translator import GoogleTranslator
import json
from docx import Document
from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    SCRAPED_WEBSITE_USER: str
    SCRAPED_WEBSITE_PASSWORD: str
    PUSHBULLET_API_KEY: str
    TRANSLATION_LANGUAGE: str = "en"

def load_config() -> Config:
    config_file = os.getenv('CONFIG_FILE', 'config.py')
    config_dict = {}
    with open(config_file, 'r') as f:
        exec(f.read(), {}, config_dict)
    return Config(
        SCRAPED_WEBSITE_USER=config_dict['SCRAPED_WEBSITE_USER'],
        SCRAPED_WEBSITE_PASSWORD=config_dict['SCRAPED_WEBSITE_PASSWORD'],
        PUSHBULLET_API_KEY=config_dict['PUSHBULLET_API_KEY'],
        TRANSLATION_LANGUAGE=config_dict.get('TRANSLATION_LANGUAGE', 'en')
    )

config = load_config()

# Enhanced logging configuration
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logging
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log", mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)

# File to store processed article IDs
PROCESSED_ARTICLES_FILE = "processed_articles.json"

def load_processed_articles():
    try:
        if os.path.exists(PROCESSED_ARTICLES_FILE):
            with open(PROCESSED_ARTICLES_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"Error loading processed articles: {e}")
        return []

def save_processed_article(article_id):
    try:
        processed = load_processed_articles()
        if article_id not in processed:
            processed.append(article_id)
            with open(PROCESSED_ARTICLES_FILE, 'w') as f:
                json.dump(processed, f)
            return True
        return False
    except Exception as e:
        logger.error(f"Error saving processed article: {e}")
        return False

def download_pdf(url, output_path):
    logger.info(f"Starting download of PDF from {url}")
    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.WRITEDATA, buffer)
    c.perform()
    c.close()

    with open(output_path, "wb") as f:
        f.write(buffer.getvalue())
    logger.info(f"PDF downloaded and saved to {output_path}")


def extract_text(pdf_path):
    logger.info(f"Extracting text from PDF {pdf_path}")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    logger.info(f"Text extraction complete for {pdf_path}")
    return text


def translate(text, src="nl", dest=config.TRANSLATION_LANGUAGE, chunk_size=4900):
    logger.info(f"Translating text from {src} to {dest}")
    translator = GoogleTranslator(source=src, target=dest)
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    translated_chunks = [translator.translate(chunk) for chunk in chunks]
    logger.info("Translation complete")
    return " ".join(translated_chunks)


def send_notification(title, body, api_key):
    try:
        logger.info(f"Sending Pushbullet notification with title: {title}")
        params = {"type": "note", "title": title, "body": body}
        response = requests.post(
            "https://api.pushbullet.com/v2/pushes",
            data=json.dumps(params),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
        )
        logger.info("Pushbullet notification sent")
    except Exception as e:
        logger.error(f"Error sending Pushbullet notification: {e}")


def process_pdf_links(playwright, browser, context, pdf_links, folder_path):
    for link in pdf_links:
        pdf_url = link.get_attribute("href")
        pdf_filename = pdf_url.split("/")[-1].split("?")[0]
        pdf_path = os.path.join(folder_path, pdf_filename)

        download_pdf(pdf_url, pdf_path)
        text = extract_text(pdf_path)

        txt_filename = pdf_filename.replace(".pdf", ".txt")
        txt_path = os.path.join(folder_path, txt_filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        send_notification(
            title=f"Original PDF: {txt_filename}",
            body=text,
            api_key=config.PUSHBULLET_API_KEY,
        )

        translated_text = translate(text)

        italian_txt_filename = pdf_filename.replace(".pdf", ".italian.txt")
        italian_txt_path = os.path.join(folder_path, italian_txt_filename)
        with open(italian_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)

        send_notification(
            title=f"Translated PDF: {italian_txt_filename}",
            body=translated_text,
            api_key=config.PUSHBULLET_API_KEY,
        )


def extract_text_from_docx(docx_path):
    logger.info(f"Extracting text from Word document {docx_path}")
    doc = Document(docx_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    logger.info(f"Text extraction complete for {docx_path}")
    return text


def process_docx_links(playwright, browser, context, docx_links, folder_path):
    for link in docx_links:
        docx_url = link.get_attribute("href")
        docx_filename = docx_url.split("/")[-1].split("?")[0]
        docx_path = os.path.join(folder_path, docx_filename)

        download_pdf(docx_url, docx_path)  # We can reuse the download_pdf function
        text = extract_text_from_docx(docx_path)

        txt_filename = docx_filename.replace(".docx", ".txt")
        txt_path = os.path.join(folder_path, txt_filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        send_notification(
            title=f"Original Word Document: {txt_filename}",
            body=text,
            api_key=config.PUSHBULLET_API_KEY,
        )

        translated_text = translate(text)

        translated_txt_filename = docx_filename.replace(".docx", ".translated.txt")
        translated_txt_path = os.path.join(folder_path, translated_txt_filename)
        with open(translated_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)

        send_notification(
            title=f"Translated Word Document: {translated_txt_filename}",
            body=translated_text,
            api_key=config.PUSHBULLET_API_KEY,
        )


def run(playwright):
    try:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        login_to_website(page)

        if "home" in page.url:
            process_first_article(playwright, browser, context, page)
        else:
            raise Exception("Login failed - URL does not contain 'home'")

        browser.close()
    except Exception as e:
        logger.error(f"Error in main run function: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def login_to_website(page):
    try:
        page.goto("https://app.socialschools.eu/home")
        page.wait_for_load_state("networkidle")

        username_field = page.locator("#username")
        if not username_field.is_visible():
            raise Exception("Username field not found")
        page.fill("#username", config.SCRAPED_WEBSITE_USER)

        password_field = page.locator("#Password")
        if not password_field.is_visible():
            raise Exception("Password field not found")
        page.fill("#Password", config.SCRAPED_WEBSITE_PASSWORD)

        page.press("#Password", "Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            raise
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def process_first_article(playwright, browser, context, page):
    try:
        logger.debug("Looking for feed element")
        feed = page.query_selector("div[role='feed']")
        if not feed:
            logger.error("Feed element not found")
            raise Exception("Feed element not found")
        logger.debug("Feed element found")
        logger.debug("Looking for first article")
        input("Press Enter to continue after checking the article...")
        first_article = feed.query_selector("div[role='article']")
        # The following code can be used to get a specific article for debugging purposes
        # all_articles = feed.query_selector_all("div[role='article']")
        # first_article = all_articles[x]
        if first_article:
            title = first_article.query_selector("h3").inner_text()
            logger.info(f"Found article: {title}")
        else:
            logger.warning("No article found in feed")
        if not first_article:
            logger.error("No article found")
            raise Exception("No article found")
        logger.debug("First article found")

        article_id = first_article.get_attribute("data-id") or first_article.get_attribute("id")
        if not article_id:
            logger.debug("No article ID found, generating from title and timestamp")
            title = first_article.query_selector("h3").inner_text()
            timestamp = first_article.query_selector("time").get_attribute("datetime") if first_article.query_selector("time") else datetime.now().isoformat()
            article_id = f"{title}_{timestamp}"
            logger.info(f"Generated article ID: {article_id}")
        else:
            logger.info(f"Found article ID: {article_id}")

        if not save_processed_article(article_id):
            logger.info(f"Article {article_id} was already processed, skipping...")
            return
        logger.info(f"Processing new article: {article_id}")

        expand_full_text(first_article)
        input("Press Enter to continue after checking the expanded text...")
        
        process_article_content(playwright, browser, context, first_article)
        
    except Exception as e:
        logger.error(f"Error processing first article: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def expand_full_text(article):
    try:
        more_button = article.query_selector("button:has-text('Meer weergeven')")
        if more_button:
            more_button.click()

        article.wait_for_selector("span[as='div']")
    except Exception as e:
        logger.error(f"Error expanding full text: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise


def process_article_content(playwright, browser, context, article):
    body = article.query_selector("span[as='div']").inner_text()
    title = article.query_selector("h3").inner_text()

    send_notification(
        title=title,
        body=body,
        api_key=config.PUSHBULLET_API_KEY,
    )

    send_notification(
        title=translate(title),
        body=translate(body),
        api_key=config.PUSHBULLET_API_KEY,
    )

    pdf_links = article.query_selector_all("a[href*='.pdf']")
    if len(pdf_links) > 0:
        process_pdf_links(playwright, browser, context, pdf_links, "")
    
    docx_links = article.query_selector_all("a[href*='.docx']")
    if len(docx_links) > 0:
        process_docx_links(playwright, browser, context, docx_links, "")
    
    if len(pdf_links) == 0 and len(docx_links) == 0:
        logger.info("No PDFs or Word documents available, sent article body in notification.")


if __name__ == "__main__":
    try:
        with sync_playwright() as playwright:
            run(playwright)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise
