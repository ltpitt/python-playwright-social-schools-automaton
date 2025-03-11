# Configuration variables, be sure to customise with your data
SCRAPED_WEBSITE_USER = "<PUT_USERNAME_HERE>"
SCRAPED_WEBSITE_PASSWORD = "<PUT_PASSWORD_HERE>"
PUSHBULLET_API_KEY = "<PUT_PUSHBULLET_API_KEY_HERE>"
TRANSLATION_LANGUAGE = "en"  # Use en,fr,it, etc

# Script logic, don't touch unless you know what you are doing :)
import os
import pycurl
import logging
from io import BytesIO
from datetime import datetime
from playwright.sync_api import sync_playwright
import fitz  # PyMuPDF
import requests
from deep_translator import GoogleTranslator
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


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


def translate(text, src="nl", dest=TRANSLATION_LANGUAGE, chunk_size=4900):
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
            api_key=PUSHBULLET_API_KEY,
        )

        translated_text = translate(text)

        italian_txt_filename = pdf_filename.replace(".pdf", ".italian.txt")
        italian_txt_path = os.path.join(folder_path, italian_txt_filename)
        with open(italian_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)

        send_notification(
            title=f"Translated PDF: {italian_txt_filename}",
            body=translated_text,
            api_key=PUSHBULLET_API_KEY,
        )


def run(playwright):
    logger.info("Launching browser")
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    logger.info("Navigating to login page")
    login_to_website(page)

    if "home" in page.url:
        logger.info("Logged in successfully")
        process_first_article(playwright, browser, context, page)

    browser.close()
    logger.info("Browser closed")


def login_to_website(page):
    page.goto("https://app.socialschools.eu/home")
    page.fill("#username", SCRAPED_WEBSITE_USER)
    page.fill("#Password", SCRAPED_WEBSITE_PASSWORD)
    page.press("#Password", "Enter")
    page.wait_for_load_state("networkidle")


def process_first_article(playwright, browser, context, page):
    feed = page.query_selector("div[role='feed']")
    first_article = feed.query_selector("div[role='article']")

    if first_article:
        logger.info("First article found")
        today = datetime.now().strftime("%Y-%m-%d")
        folder_path = os.path.join(os.getcwd(), today)

        if not os.path.exists(folder_path):
            logger.info("News were not sent previously today")
            expand_full_text(first_article)
            process_article_content(
                playwright, browser, context, first_article, folder_path
            )
        else:
            logger.info("News were already sent today, quitting...")
    else:
        logger.info("No article found, quitting...")


def expand_full_text(article):
    more_button = article.query_selector("button:has-text('Meer weergeven')")
    if more_button:
        more_button.click()
        logger.info("Clicked 'Meer weergeven' button to expand the full text")
    article.wait_for_selector("span[as='div']")


def process_article_content(playwright, browser, context, article, folder_path):
    body = article.query_selector("span[as='div']").inner_text()

    title = article.query_selector("h3").inner_text()

    send_notification(
        title=title,
        body=body,
        api_key=PUSHBULLET_API_KEY,
    )

    send_notification(
        title=translate(title),
        body=translate(body),
        api_key=PUSHBULLET_API_KEY,
    )

    os.makedirs(folder_path)
    logger.info(f"Created folder {folder_path}")

    pdf_links = article.query_selector_all("a[href*='.pdf']")
    if len(pdf_links) > 0:
        process_pdf_links(playwright, browser, context, pdf_links, folder_path)
    else:
        logger.info("No PDFs available, sent article body in notification.")


with sync_playwright() as playwright:
    run(playwright)
