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
        return pd.DataFrame()

    columns = df_raw.iloc[header_row_idx].astype(str).str.strip()
    data_rows = df_raw.iloc[header_row_idx + 1:].reset_index(drop=True)

    current_category = None
    parsed_rows = []

    for _, row in data_rows.iterrows():
        row_clean = row.dropna().astype(str).str.strip().tolist()

        if not row_clean:
            continue

        # A category row has 1 non-numeric text value and no headers
        if len(row_clean) == 1 and re.match(r'^[A-Z\s/&\-]+$', row_clean[0], re.IGNORECASE):
            current_category = row_clean[0]
            continue

        try:
            row_dict = dict(zip(columns, row.tolist()))
            if str(row_dict.get("LIQUOR", "")).strip().isdigit():
                parsed_rows.append({
                    "CODE": str(row_dict.get("LIQUOR", "")).strip(),
                    "Brand": str(row_dict.get("BRAND NAME", "")).strip(),
                    "Proof": pd.to_numeric(row_dict.get("PROOF", None), errors='coerce'),
                    "List Price": pd.to_numeric(row_dict.get("LICENSEE", None), errors='coerce'),
                    "ADA": str(row_dict.get("ADA", "")).strip(),
                    "Category": current_category,
                    "Date Added": date_added.strftime('%Y-%m-%d')
                })
        except Exception as e:
            continue

    return pd.DataFrame(parsed_rows)

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
