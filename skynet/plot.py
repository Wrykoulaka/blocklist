#!/usr/bin/env python3
import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import requests

FILTER_FILE = "filter.list"

COUNTS_HISTORY_FILE = "ip_counts_history.csv"
GRAPH_FILE = "ip_counts_graph.png"

MAX_THREADS = 8
MAX_ENTRIES = 60


def fetch_url_content(url):
    try:
        print(f"Fetching {url}")
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[ERROR] Failed to fetch {url}: {e}")
        return ""


def extract_ips_from_text(text):
    ip_pattern = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}" r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b")
    return set(ip_pattern.findall(text))


def trim_history():
    """Keep only the last MAX_ENTRIES rows in the history CSV"""
    if not os.path.isfile(COUNTS_HISTORY_FILE):
        return

    with open(COUNTS_HISTORY_FILE, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if len(rows) <= 1:  # only header or empty
        return

    header, data = rows[0], rows[1:]
    if len(data) > MAX_ENTRIES:
        data = data[-MAX_ENTRIES:]  # keep only last 60

        with open(COUNTS_HISTORY_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(data)


def log_count_to_history(date_str, unique_count):
    rows = []
    if os.path.isfile(COUNTS_HISTORY_FILE):
        with open(COUNTS_HISTORY_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    updated = False
    for r in rows:
        if r["date"] == date_str:
            r["unique_ips"] = str(unique_count)
            updated = True
            break
    if not updated:
        rows.append({"date": date_str, "unique_ips": str(unique_count)})

    # sort by date ascending
    rows_sorted = sorted(rows, key=lambda x: x["date"])

    with open(COUNTS_HISTORY_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "unique_ips"])
        writer.writeheader()
        writer.writerows(rows_sorted)

    # Trim to last MAX_ENTRIES
    trim_history()


def generate_graph():
    dates, counts = [], []
    if not os.path.isfile(COUNTS_HISTORY_FILE):
        print(f"No history file {COUNTS_HISTORY_FILE} found, skipping graph generation.")
        return
    with open(COUNTS_HISTORY_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row["date"], "%Y-%m-%d")
                cnt = int(row["unique_ips"])
                dates.append(dt)
                counts.append(cnt)
            except Exception:
                continue
    if not dates:
        print("No data to plot.")
        return

    latest_value = f"{counts[-1]:,}"
    latest_date = dates[-1].strftime("%Y-%m-%d")

    plt.figure(figsize=(8, 4))
    plt.plot(dates, counts, marker="o", linestyle="-", color="green")

    # Format y-axis with commas
    plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    plt.title(f"Unique IPs Over Time (Latest: {latest_value} on {latest_date})")
    plt.xlabel("Date")
    plt.xticks(rotation=90)
    plt.ylabel("Unique IPs")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(GRAPH_FILE)
    plt.close()
    print(f"Graph saved to {GRAPH_FILE}")


def main():
    try:
        if not os.path.isfile(FILTER_FILE):
            print(f"No filter list file found: {FILTER_FILE}")
            return

        with open(FILTER_FILE, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        unique_ips = set()
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {executor.submit(fetch_url_content, url): url for url in urls}
            for future in as_completed(futures):
                content = future.result()
                if content:
                    ips = extract_ips_from_text(content)
                    unique_ips.update(ips)

        count = len(unique_ips)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        print(f"Total unique IP addresses found: {count}")

        log_count_to_history(date_str, count)
        generate_graph()

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
