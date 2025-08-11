#!/usr/bin/env python3
import os
import requests
from io import StringIO
import sys
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SOURCES_FILE = os.getenv("SOURCES_FILE", "sources.txt")  # Default: sources.txt in repo

MAX_THREADS = 8  # Number of parallel downloads

SOURCE_LIST_URL = "https://v.firebog.net/hosts/lists.php?type=tick"

def send_telegram_message(message):
    """Send a message to Telegram using the bot token and chat ID."""
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        print("[WARNING] Telegram bot token or chat ID not set. Skipping notification.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")

def update_sources_file():
    """Fetch the list from SOURCE_LIST_URL, overwrite sources.txt, then append additional_sources.txt."""
    try:
        print(f"Fetching source list from {SOURCE_LIST_URL}")
        resp = requests.get(SOURCE_LIST_URL, timeout=20)
        resp.raise_for_status()
        content = resp.text
        
        # Write main sources to SOURCES_FILE
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {SOURCES_FILE} with content from {SOURCE_LIST_URL}")

        # Append additional sources if file exists
        additional_file = "additional_sources.txt"
        if os.path.isfile(additional_file):
            with open(additional_file, "r", encoding="utf-8") as af, open(SOURCES_FILE, "a", encoding="utf-8") as f:
                lines = af.readlines()
                # Filter out empty lines and comments before appending
                lines_to_add = [line for line in lines if line.strip() and not line.startswith("#")]
                if lines_to_add:
                    f.write("\n")  # Ensure a newline before appending
                    f.writelines(lines_to_add)
            print(f"Appended entries from {additional_file} to {SOURCES_FILE}")
        else:
            print(f"No additional sources file found at {additional_file}, skipping append.")

    except Exception as e:
        error_message = f"[ERROR] Failed to update sources file from {SOURCE_LIST_URL}: {e}"
        print(error_message)
        send_telegram_message(error_message)
        sys.exit(1)

def load_urls(file_path):
    """Load URLs from a text file, skipping comments and blanks."""
    urls = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except FileNotFoundError:
        error_message = f"[ERROR] Sources file not found: {file_path}"
        print(error_message)
        send_telegram_message(error_message)
        sys.exit(1)
    return urls

def download_list(url):
    """Download a hosts or adblock list from a given URL."""
    try:
        print(f"Downloading: {url}")
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return url, resp.text
    except Exception as e:
        error_message = f"[ERROR] Could not download {url}: {e}"
        print(error_message)
        send_telegram_message(error_message)
        return url, ""

def normalize_adblock_line(line):
    """
    Convert Adblock-style rules to plain domain if possible.
    Examples:
    - ||domain.com^  -> domain.com
    - |http://domain.com| -> domain.com
    Returns domain string or None if not recognized.
    """
    # Remove common Adblock prefixes/suffixes:
    # Start with ||
    if line.startswith("||"):
        domain = line[2:]
        domain = domain.split("^")[0]
        domain = domain.strip()
        if domain:
            return domain.lower()
    # Start with single | (rare)
    if line.startswith("|"):
        domain = line.lstrip("|").rstrip("|")
        # Remove scheme if present
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("^")[0]
        domain = domain.strip()
        if domain:
            return domain.lower()
    # Plain domain or wildcard rules (skip wildcards)
    if line and "*" not in line and "/" not in line and "|" not in line and "^" not in line:
        # Basic domain validation
        if re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", line):
            return line.lower()
    return None

def parse_hosts(text):
    """Extract valid domains from a hosts file or adblock-style list."""
    domains = set()
    for line in StringIO(text):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # Normal hosts entries: "0.0.0.0 domain" or "127.0.0.1 domain"
        if len(parts) >= 2 and parts[0] in ["0.0.0.0", "127.0.0.1"]:
            domain = parts[1].lower()
            domains.add(domain)
            continue
        # Sometimes a single domain per line (some adblock lists)
        if len(parts) == 1:
            domain_candidate = normalize_adblock_line(parts[0])
            if domain_candidate:
                domains.add(domain_candidate)
                continue
        # If line looks like an adblock filter (||domain^)
        domain_candidate = normalize_adblock_line(line)
        if domain_candidate:
            domains.add(domain_candidate)
    return domains

def main():
    try:
        # Update sources.txt at the start from the URL and append additional entries
        update_sources_file()

        urls = load_urls(SOURCES_FILE)
        all_domains = set()
        domains_per_source = {}

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {executor.submit(download_list, url): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    _, text = future.result()
                    if text:
                        domains = parse_hosts(text)
                        domains_per_source[url] = len(domains)
                        all_domains.update(domains)
                    else:
                        domains_per_source[url] = 0
                except Exception as e:
                    msg = f"[ERROR] Exception processing {url}: {e}"
                    print(msg)
                    send_telegram_message(msg)
                    domains_per_source[url] = 0

        total_unique = len(all_domains)
        released_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        print("Entries per source:")
        for source_url, count in domains_per_source.items():
            print(f"  {source_url} -> {count} domains")

        with open("unified_hosts.txt", "w", encoding="utf-8") as f:
            # Write header
            f.write("# Title: Wakuvilla/hosts\n")
            f.write("# Description: Merged hosts from reputable sources\n")
            f.write(f"# Sources list updated dynamically from: {SOURCE_LIST_URL}\n")
            f.write(f"# Last updated: {released_time}\n")
            f.write("# Expires: 6 hours\n")
            f.write(f"# Number of unique domains: {total_unique}\n")
            f.write("#\n")
            f.write("# Domains per source:\n")
            for source_url, count in domains_per_source.items():
                f.write(f"# {source_url} -> {count} domains\n")
            f.write("#\n\n")
            # Write domains in hosts format
            for domain in sorted(all_domains):
                f.write(f"0.0.0.0 {domain}\n")

        print(f"File 'unified_hosts.txt' generated with {total_unique} domains.")

    except Exception:
        error_details = "".join(traceback.format_exception(*sys.exc_info()))
        send_telegram_message(f"Github action blocklist error\n⚠️ *Script Error*\n```\n{error_details}\n```")
        raise

if __name__ == "__main__":
    main()
