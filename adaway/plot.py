#!/usr/bin/env python3
import os
import csv
from datetime import datetime
import matplotlib.pyplot as plt

COUNTS_HISTORY_FILE = "counts_history.csv"
GRAPH_FILE = "counts_graph.png"

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
    plt.figure(figsize=(8, 4))
    plt.plot(dates, counts, marker='o', linestyle='-', color='blue')
    plt.title("Unique Domains in unified_hosts.txt Over Time")
    plt.xlabel("Date")
    plt.ylabel("Number of Unique Domains")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(GRAPH_FILE)
    plt.close()
    print(f"Graph saved to {GRAPH_FILE}")

if __name__ == "__main__":
    generate_graph()
