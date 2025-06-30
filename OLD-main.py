import os
import sys
import json
import logging
import requests
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

# Load environment
load_dotenv()
APP_NAME = os.getenv("APP_NAME", "whiskey_bot")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AI_NODE_ADDRESS = os.getenv("TELEGRAM_CHAT_ID")

# Constants
BASE_URL = "https://www.michigan.gov"
PAGE_URL = f"{BASE_URL}/lara/bureau-list/lcc/spirits-price-book-info"
DOWNLOAD_DIR = "./downloads"
MASTER_FILE = "master_list.csv"
SEEN_LINKS_FILE = "seen_links.json"

# Logging setup
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format=f'{{"app_name": "{APP_NAME}", "timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

def ensure_directories():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    if not os.path.exists(SEEN_LINKS_FILE):
        with open(SEEN_LINKS_FILE, "w") as f:
            json.dump([], f)

def load_seen_links():
    with open(SEEN_LINKS_FILE, 'r') as f:
        return set(json.load(f))

def save_seen_links(links):
    with open(SEEN_LINKS_FILE, 'w') as f:
        json.dump(sorted(list(links)), f, indent=2)

def find_excel_links():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(PAGE_URL)

    elements = driver.find_elements(By.TAG_NAME, "a")
    links = set()

    for elem in elements:
        href = elem.get_attribute("href")
        text = elem.text.strip().lower()
        if href and ("xlsx" in href or "xls" in href) and "price" in text:
            links.add(href)

    driver.quit()
    return links

def download_file(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Referer": PAGE_URL,
    }

    filename = os.path.join(DOWNLOAD_DIR, os.path.basename(url.split("?")[0]))  # Strip URL params
    if not os.path.exists(filename):
        logging.info(f"Downloading: {url}")
        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(r.content)
            return filename
        except Exception as e:
            logging.error(f"Download failed: {e}")
            return None
    else:
        logging.info(f"Already downloaded: {filename}")
        return filename

def compare_to_master(new_file):
    new_df = pd.read_excel(new_file)
    if 'Item Code' not in new_df.columns:
        logging.warning("Missing 'Item Code' column.")
        return pd.DataFrame(), pd.DataFrame()

    if not os.path.exists(MASTER_FILE):
        new_df.to_csv(MASTER_FILE, index=False)
        return new_df, pd.DataFrame()

    master_df = pd.read_csv(MASTER_FILE)

    new_set = set(new_df['Item Code'].astype(str))
    master_set = set(master_df['Item Code'].astype(str))

    added = new_df[new_df['Item Code'].astype(str).isin(new_set - master_set)]
    removed = master_df[master_df['Item Code'].astype(str).isin(master_set - new_set)]

    new_df.to_csv(MASTER_FILE, index=False)
    return added, removed

def generate_summary(added, removed):
    prompt = "Write a clever and engaging summary about these whiskey changes:\n"
    if not added.empty:
        prompt += f"\n### New Whiskeys:\n{added[['Item Code','Brand','Proof']].head(5).to_string(index=False)}"
    if not removed.empty:
        prompt += f"\n\n### Discontinued Whiskeys:\n{removed[['Item Code','Brand','Proof']].head(5).to_string(index=False)}"

    import subprocess
    result = subprocess.run(["ollama", "run", "mistral", prompt], capture_output=True, text=True)
    return result.stdout

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials not configured.")
        return
    try:
        import telegram
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        logging.info("Telegram message sent.")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def main():
    ensure_directories()

    seen_links = load_seen_links()
    current_links = find_excel_links()
    new_links = current_links - seen_links

    logging.info(f"Found {len(current_links)} total links.")
    logging.info(f"Detected {len(new_links)} new link(s).")

    for url in new_links:
        file = download_file(url)
        if file:
            added, removed = compare_to_master(file)
            if not added.empty or not removed.empty:
                summary = generate_summary(added, removed)
                logging.info("Generated summary from Ollama.")
                send_telegram(summary)
            else:
                logging.info("No changes detected.")
        else:
            logging.warning(f"Failed to handle: {url}")

    seen_links.update(new_links)
    save_seen_links(seen_links)

if __name__ == "__main__":
    main()
