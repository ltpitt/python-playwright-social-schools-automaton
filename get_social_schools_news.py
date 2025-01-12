# Configuration variables, be sure to customise with your data
SCRAPED_WEBSITE_USER = "<PUT_USERNAME_HERE>"
SCRAPED_WEBSITE_PASSWORD = "<PUT_PASSWORD_HERE>"
PUSHBULLET_API_KEY = "<PUT_PUSHBULLET_API_KEY_HERE>"
TRANSLATION_LANGUAGE = "it"  # Use en,fr,it, etc

# Script logic, don't touch unless you know what you are doing :)
import os
import pycurl
import logging
from io import BytesIO
from datetime import datetime
from playwright.sync_api import sync_playwright
import fitz  # PyMuPDF
from deep_translator import GoogleTranslator
import requests
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def download_pdf_with_pycurl(url, output_path):
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


def extract_text_from_pdf(pdf_path):
    logger.info(f"Extracting text from PDF {pdf_path}")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    logger.info(f"Text extraction complete for {pdf_path}")
    return text


def translate_text(text, src="nl", dest=TRANSLATION_LANGUAGE, chunk_size=4900):
    logger.info(f"Translating text from {src} to {dest}")
    translator = GoogleTranslator(source=src, target=dest)
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    translated_chunks = [translator.translate(chunk) for chunk in chunks]
    logger.info("Translation complete")
    return " ".join(translated_chunks)


def send_pushbullet_notification(title, body, api_key):
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
    logger.info(response)
    logger.info("Pushbullet notification sent")


def run(playwright):
    today = datetime.now().strftime("%Y-%m-%d")
    today_date = datetime.strptime(today, "%Y-%m-%d")
    folder_path = os.path.join(os.getcwd(), today)

    logger.info("Launching browser")
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    logger.info("Navigating to login page")
    page.goto("https://app.socialschools.eu/home")
    page.fill("#username", SCRAPED_WEBSITE_USER)
    page.fill("#Password", SCRAPED_WEBSITE_PASSWORD)
    page.press("#Password", "Enter")
    page.wait_for_load_state("networkidle")

    if "home" in page.url:
        logger.info("Logged in successfully")
        feed = page.query_selector("div[role='feed']")
        first_article = feed.query_selector("div[role='article']")

        if first_article:
            title = first_article.query_selector("h3").inner_text()
            date_text = title.split(", ")[-1]
            date = datetime.strptime(date_text, "%d %B %Y")

            if date == today_date:
                folder_name = date.strftime("%Y-%m-%d")
                folder_path = os.path.join(os.getcwd(), folder_name)

                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)
                    logger.info(f"Created folder {folder_path}")

                    pdf_links = first_article.query_selector_all("a[href*='.pdf']")

                    for link in pdf_links:
                        pdf_url = link.get_attribute("href")
                        pdf_filename = pdf_url.split("/")[-1].split("?")[0]
                        pdf_path = os.path.join(folder_path, pdf_filename)

                        download_pdf_with_pycurl(pdf_url, pdf_path)
                        text = extract_text_from_pdf(pdf_path)

                        txt_filename = pdf_filename.replace(".pdf", ".txt")
                        txt_path = os.path.join(folder_path, txt_filename)
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(text)

                        translated_text = translate_text(text)

                        italian_txt_filename = pdf_filename.replace(
                            ".pdf", ".italian.txt"
                        )
                        italian_txt_path = os.path.join(
                            folder_path, italian_txt_filename
                        )
                        with open(italian_txt_path, "w", encoding="utf-8") as f:
                            f.write(translated_text)

                        send_pushbullet_notification(
                            title=f"Translated Document: {italian_txt_filename}",
                            body=translated_text,
                            api_key=PUSHBULLET_API_KEY,
                        )
            else:
                logger.info("No new updates for today, quitting...")
                exit()

    browser.close()
    logger.info("Browser closed")


with sync_playwright() as playwright:
    run(playwright)
