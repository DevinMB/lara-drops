import os
import json
import logging
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# Constants
BASE_URL = "https://www.michigan.gov"
PAGE_URL = f"{BASE_URL}/lara/bureau-list/lcc/spirits-price-book-info"
DOWNLOAD_DIR = "./downloads"
MASTER_FILE = "master_list.xlsx"
SEEN_LINKS_FILE = "seen_links.json"

logging.basicConfig(level=logging.INFO)

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
        if href and text.endswith("price book (excel)"):
            links.add(href)

    driver.quit()
    return links

def download_file(url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": PAGE_URL,
    }
    filename = os.path.join(DOWNLOAD_DIR, os.path.basename(url.split("?")[0]))
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

def parse_and_clean_excel(file_path):
    df_raw = pd.read_excel(file_path, header=None)
    date_match = re.search(r"(\d{1,2}-\d{1,2}-\d{2})", file_path)
    date_added = pd.to_datetime(date_match.group(1)) if date_match else pd.Timestamp.now()

    header_row_idx = None
    for idx, row in df_raw.iterrows():
        cleaned = row.dropna().astype(str).str.strip().str.lower()
        hits = sum([
            any("liquor" in col for col in cleaned),
            any("brand name" in col for col in cleaned),
            any("proof" in col for col in cleaned),
        ])
        if hits >= 2:
            header_row_idx = idx
            break

    if header_row_idx is None:
        logging.warning("Header row not found.")
        logging.warning("Could not find header row. Showing first 10 rows for debugging:")
        logging.warning(df_raw.head(10).to_string())
        return pd.DataFrame()

    df = pd.read_excel(file_path, header=header_row_idx)
    df.columns = df.columns.astype(str).str.strip()
    logging.info(f"Parsed columns: {df.columns.tolist()}")

    required_columns = ['LIQUOR', 'BRAND NAME', 'PROOF', 'LICENSEE', 'ADA']
    for col in required_columns:
        if col not in df.columns:
            logging.warning(f"Required column '{col}' not found in parsed DataFrame.")
            return pd.DataFrame()

    df = df[df['LIQUOR'].notna() & df['LIQUOR'].astype(str).str.isdigit()]

    # Backfill category
    categories = []
    for idx in df.index:
        raw_row_idx = header_row_idx + 1 + (idx - df.index[0])
        candidates = df_raw.loc[max(0, raw_row_idx-5):raw_row_idx, 0].dropna().astype(str).str.strip()
        candidates = candidates[candidates.str.match(r'^[A-Z\s/&]+$', na=False) & ~candidates.str.contains("LIQUOR")]
        category = candidates.iloc[-1] if not candidates.empty else None
        categories.append(category)

    df['Category'] = categories
    df['Date Added'] = date_added.strftime('%Y-%m-%d')

    df['CODE'] = df['LIQUOR'].astype(str).str.strip()
    df['Brand'] = df['BRAND NAME'].astype(str).str.strip()
    df['Proof'] = pd.to_numeric(df['PROOF'], errors='coerce')
    df['List Price'] = pd.to_numeric(df['LICENSEE'], errors='coerce')
    df['ADA'] = df['ADA'].astype(str).str.strip()

    return df[['CODE', 'Brand', 'Proof', 'List Price', 'ADA', 'Category', 'Date Added']]

def compare_to_master(new_file):
    new_df = parse_and_clean_excel(new_file)

    if new_df.empty or 'CODE' not in new_df.columns:
        logging.warning("Parsed DataFrame is empty or missing 'CODE'.")
        return pd.DataFrame(), pd.DataFrame()

    if not os.path.exists(MASTER_FILE):
        new_df.to_excel(MASTER_FILE, index=False)
        return new_df, pd.DataFrame()

    master_df = pd.read_excel(MASTER_FILE)
    new_set = set(new_df['CODE'].astype(str))
    master_set = set(master_df['CODE'].astype(str))

    added = new_df[new_df['CODE'].astype(str).isin(new_set - master_set)]
    removed = master_df[master_df['CODE'].astype(str).isin(master_set - new_set)]

    new_df.to_excel(MASTER_FILE, index=False)
    return added, removed