#!/usr/bin/env python3
import csv
import os
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

COUNTS_HISTORY_FILE = "counts_history.csv"
GRAPH_FILE = "counts_graph.png"
MAX_ENTRIES = 60


def trim_history():
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


def generate_graph():
    dates = []
    counts = []
    if not os.path.isfile(COUNTS_HISTORY_FILE):
        print(f"No history file {COUNTS_HISTORY_FILE} found, skipping graph generation.")
        return
    with open(COUNTS_HISTORY_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row["date"], "%Y-%m-%d")
                cnt = int(row["unique_domains"])
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
    plt.plot(dates, counts, marker="o", linestyle="-", color="blue")

    # Format y-axis with commas
    plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    plt.title(f"Unique Domains Over Time (Latest: {latest_value} on {latest_date})")
    plt.xlabel("Date")
    plt.ylabel("Unique Domains")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(GRAPH_FILE)
    plt.close()
    print(f"Graph saved to {GRAPH_FILE}")


if __name__ == "__main__":
    trim_history()
    generate_graph()
