#!/usr/bin/env python3
import csv
import os
import re
import sys
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import StringIO

import matplotlib.pyplot as plt
import requests

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SOURCES_FILE = os.getenv("SOURCES_FILE", "sources.txt")  # Default: sources.txt in repo

MAX_THREADS = 8  # Number of parallel downloads

SOURCE_LIST_URL = "https://v.firebog.net/hosts/lists.php?type=tick"

COUNTS_HISTORY_FILE = "counts_history.csv"
GRAPH_FILE = "counts_graph.png"
ERROR_TRACKER_FILE = "error_tracker.json"


# ---------------- Telegram ----------------
def send_telegram_message(message):
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


# ---------------- Error tracker ----------------
def load_error_tracker():
    if os.path.isfile(ERROR_TRACKER_FILE):
        with open(ERROR_TRACKER_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_error_tracker(data):
    with open(ERROR_TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def should_skip_url(url, tracker):
    info = tracker.get(url, {})
    skip_until = info.get("skip_until")
    if skip_until:
        try:
            skip_date = datetime.strptime(skip_until, "%Y-%m-%d").date()
            if skip_date > datetime.utcnow().date():
                print(f"[INFO] Skipping {url} (blocked until {skip_until})")
                return True
        except ValueError:
            pass
    return False

def record_result(url, success, tracker):
    entry = tracker.get(url, {"consecutive_errors": 0, "skip_until": None})
    if success:
        if entry["consecutive_errors"] > 0 or entry["skip_until"]:
            msg = f"[INFO] {url} recovered successfully. Resetting error count."
            print(msg)
            send_telegram_message(msg)
        entry["consecutive_errors"] = 0
        entry["skip_until"] = None
    else:
        entry["consecutive_errors"] += 1
        count = entry["consecutive_errors"]
        if count < 3:
            msg = f"[WARNING] {url} failed ({count}/3)."
            print(msg)
            send_telegram_message(msg)
        else:
            skip_date = (datetime.utcnow().date() + timedelta(days=60)).strftime("%Y-%m-%d")
            entry["skip_until"] = skip_date
            msg = f"[WARNING] {url} failed 3 times. It will be skipped until {skip_date}."
            print(msg)
            send_telegram_message(msg)
    tracker[url] = entry


# ---------------- Sources ----------------
def update_sources_file():
    try:
        print(f"Fetching source list from {SOURCE_LIST_URL}")
        resp = requests.get(SOURCE_LIST_URL, timeout=20)
        resp.raise_for_status()
        content = resp.text

        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {SOURCES_FILE} with content from {SOURCE_LIST_URL}")

        additional_file = "additional_sources.txt"
        if os.path.isfile(additional_file):
            with open(additional_file, "r", encoding="utf-8") as af, open(SOURCES_FILE, "a", encoding="utf-8") as f:
                lines = af.readlines()
                lines_to_add = [line for line in lines if line.strip() and not line.startswith("#")]
                if lines_to_add:
                    f.write("\n")  # newline before appending
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


# ---------------- Download & Parse ----------------
def download_list(url):
    try:
        print(f"Downloading: {url}")
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return url, resp.text
    except Exception as e:
        error_message = f"[ERROR] Could not download {url}: {e}"
        print(error_message)
        return url, ""


def normalize_adblock_line(line):
    if line.startswith("||"):
        domain = line[2:].split("^")[0].strip()
        if domain:
            return domain.lower()
    if line.startswith("|"):
        domain = line.lstrip("|").rstrip("|")
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("^")[0].strip()
        if domain:
            return domain.lower()
    if line and "*" not in line and "/" not in line and "|" not in line and "^" not in line:
        if re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", line):
            return line.lower()
    return None


def parse_hosts(text):
    domains = set()
    for line in StringIO(text):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ["0.0.0.0", "127.0.0.1"]:
            domains.add(parts[1].lower())
            continue
        if len(parts) == 1:
            candidate = normalize_adblock_line(parts[0])
            if candidate:
                domains.add(candidate)
                continue
        candidate = normalize_adblock_line(line)
        if candidate:
            domains.add(candidate)
    return domains


# ---------------- History ----------------
def log_count_to_history(date_str, count):
    history = []
    cutoff_date = datetime.utcnow().date() - timedelta(days=30)

    if os.path.isfile(COUNTS_HISTORY_FILE):
        with open(COUNTS_HISTORY_FILE, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    if row_date >= cutoff_date:
                        history.append({"date": row["date"], "unique_domains": int(row["unique_domains"])})
                except Exception:
                    continue

    # Update or add today's entry
    today_found = False
    for entry in history:
        if entry["date"] == date_str:
            entry["unique_domains"] = count
            today_found = True
            break
    if not today_found:
        history.append({"date": date_str, "unique_domains": count})

    history.sort(key=lambda x: x["date"])

    with open(COUNTS_HISTORY_FILE, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["date", "unique_domains"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in history:
            writer.writerow({"date": row["date"], "unique_domains": row["unique_domains"]})


# ---------------- Main ----------------
def main():
    try:
        update_sources_file()

        urls = load_urls(SOURCES_FILE)
        all_domains = set()
        domains_per_source = {}

        error_tracker = load_error_tracker()

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {}
            for url in urls:
                if should_skip_url(url, error_tracker):
                    domains_per_source[url] = 0
                    continue
                futures[executor.submit(download_list, url)] = url

            for future in as_completed(futures):
                url = futures[future]
                try:
                    _, text = future.result()
                    if text:
                        domains = parse_hosts(text)
                        domains_per_source[url] = len(domains)
                        all_domains.update(domains)
                        record_result(url, True, error_tracker)
                    else:
                        domains_per_source[url] = 0
                        record_result(url, False, error_tracker)
                except Exception as e:
                    msg = f"[ERROR] Exception processing {url}: {e}"
                    print(msg)
                    send_telegram_message(msg)
                    domains_per_source[url] = 0
                    record_result(url, False, error_tracker)

        save_error_tracker(error_tracker)

        total_unique = len(all_domains)
        released_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

        print("Entries per source:")
        for source_url, count in domains_per_source.items():
            print(f"  {source_url} -> {count} domains")

        with open("unified_hosts.txt", "w", encoding="utf-8") as f:
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
            for domain in sorted(all_domains):
                f.write(f"0.0.0.0 {domain}\n")

        print(f"File 'unified_hosts.txt' generated with {total_unique} domains.")

        # Log count to CSV history (last 30 days only)
        log_count_to_history(date_str, total_unique)

    except Exception:
        error_details = "".join(traceback.format_exception(*sys.exc_info()))
        send_telegram_message(f"Github action blocklist error\n⚠️ *Script Error*\n```\n{error_details}\n```")
        raise


if __name__ == "__main__":
    main()