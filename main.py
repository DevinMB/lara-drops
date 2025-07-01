import os
import logging
import sys
from dotenv import load_dotenv

from lara_service import (
    ensure_directories,
    load_seen_links,
    save_seen_links,
    find_excel_links,
    download_file,
    compare_to_master
)
from ai_service import generate_summary
from telegram_bot_service import send_telegram

load_dotenv()
APP_NAME = os.getenv("APP_NAME")

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format=f'{{"app_name": "{APP_NAME}", "timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

def main():
    ensure_directories()

    seen_links = load_seen_links()
    current_links = find_excel_links()
    new_links = current_links - seen_links

    logging.info(f"Found {len(current_links)} total links.")
    logging.info(f"Detected {len(new_links)} new link(s).")

    for url in new_links:
        file_path = download_file(url)
        if not file_path:
            logging.warning(f"Failed to handle: {url}")
            continue

        added, removed = compare_to_master(file_path)
        if added.empty and removed.empty:
            logging.info("No changes detected.")
            continue

        logging.info(f"Adds: {added}")
        logging.info(f"Removes: {removed}")
        # TODO: add descriptions to objects
        # additionalInfo = generate_descriptions()
        summary = generate_summary(added, removed)
        if summary:
            logging.info("Generated summary from Ollama.")
            logging.info(f"Telegram summary:\n{summary}")
            send_telegram(summary)
        else:
            logging.warning("No summary generated.")

    seen_links.update(new_links)
    save_seen_links(seen_links)

if __name__ == "__main__":
    main()
