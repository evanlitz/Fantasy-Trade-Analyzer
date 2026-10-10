import csv
import io
import re
import time

import requests
from bs4 import BeautifulSoup

from common import HEADERS, write_csv
from ids import assign_ids

# The chart is a new article each month, so find the latest one from the dynasty index
INDEX_URL = "https://www.fantasypros.com/nfl/articles/dynasty.php"
DATAWRAPPER = "https://datawrapper.dwcdn.net"
POSITIONS = {"Quarterbacks": "QB", "Running Backs": "RB", "Wide Receivers": "WR", "Tight Ends": "TE"}
DELAY = 1.5

# 2028 picks are bucketed by slot range. FantasyPros' own tiers, not the thirds-of-a-round used elsewhere
PICK_RANGE_TIERS = {
    "1.01-1.03": "early",
    "1.04-1.06": "mid",
    "1.07-1.12": "late",
}


def get(url):
    time.sleep(DELAY)
    return requests.get(url, headers=HEADERS, timeout=60)


def latest_article():
    links = re.findall(r'href="(https://www\.fantasypros\.com/(\d{4})/(\d{1,2})/[^"]*dynasty-trade-value-chart[^"]*)"', get(INDEX_URL).text)
    return max(links, key=lambda m: (int(m[1]), int(m[2])))[0]


def datawrapper_rows(chart_id):
    # Embeds point at an old version that meta-refreshes to the current one; follow it to the end
    url = f"{DATAWRAPPER}/{chart_id}/"
    while m := re.search(r'http-equiv="REFRESH" content="0; url=([^"]+)"', get(url).text):
        url = m[1]
    return list(csv.DictReader(io.StringIO(get(url + "dataset.csv").text), delimiter="\t"))


def pick_name(year, label):
    if m := re.fullmatch(r"(\d)\.(\d{2})", label):
        return f"{year} Pick {m[1]}.{m[2]}"
    if re.fullmatch(r"(Early|Mid|Late) \d(?:st|nd|rd|th)", label):
        return f"{year} {label}"
    if m := re.fullmatch(r"(\d\.\d{2})\D+(\d\.\d{2})", label):
        tier = PICK_RANGE_TIERS.get(f"{m[1]}-{m[2]}")
        return tier and f"{year} {tier.title()} {m[1][0]}{'st' if m[1][0] == '1' else 'nd'}"
    return None


def pull():
    soup = BeautifulSoup(get(latest_article()).content, "html.parser")
    rows = []
    for iframe in soup.find_all("iframe", src=re.compile(r"datawrapper\.dwcdn\.net")):
        heading = iframe.find_previous("h3").get_text()
        position = next(p for k, p in POSITIONS.items() if k in heading)
        for r in datawrapper_rows(iframe["src"].split("/")[3]):
            # each chart ends with an "All Other QBs"-style catch-all row
            if r["Name"].startswith("All Other"):
                continue
            rows.append({
                "Player Name": r["Name"],
                "Type": "Player",
                "Position": position,
                "Team": r["Team"],
                "Age": float(r["Age"]) if r["Age"] else None,
                "Value": int(r["Trade Value"]),
                "Asset ID": None,
            })

    for table in soup.find_all("table"):
        title = table.find_previous(string=re.compile(r"\d{4} Dynasty Rookie Draft Pick Values"))
        if not title:
            continue
        year = re.search(r"\d{4}", title)[0]
        for tr in table.find_all("tr")[1:]:
            label, value_1qb, _ = (td.get_text(strip=True) for td in tr.find_all("td"))
            name = pick_name(year, label)
            if not name:
                print(f"  fantasypros: skipped pick row {year} {label!r}")
                continue
            rows.append({"Player Name": name, "Type": "Pick", "Position": "PICK", "Team": None, "Age": None,
                         "Value": int(value_1qb), "Asset ID": None})
    write_csv("fantasypros", assign_ids("fantasypros", rows))


if __name__ == "__main__":
    pull()
