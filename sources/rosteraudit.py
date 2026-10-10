import requests

from common import HEADERS, write_csv
from ids import assign_ids

BASE = "https://rosteraudit.com/wp-json/ra/v1"


def pull():
    rows = []
    page = 1
    while True:
        data = requests.get(f"{BASE}/rankings", params={"format": "1qb", "per_page": 100, "page": page}, headers=HEADERS, timeout=60).json()
        # picks come from /picks below, which matches these values and adds 5th rounds
        for p in data["players"]:
            if p["position"] == "PICK":
                continue
            rows.append({
                "Player Name": p["name"],
                "Type": "Player",
                "Position": p["position"],
                "Team": p["team"],
                "Age": float(p["age"]) if p["age"] else None,
                "Value": p["value"],
                "Asset ID": p["sleeper_id"],
            })
        if page >= data["total_pages"]:
            break
        page += 1

    for pick in requests.get(f"{BASE}/picks", headers=HEADERS, timeout=60).json()["picks"]:
        rows.append({
            "Player Name": pick["label"],
            "Type": "Pick",
            "Position": "PICK",
            "Team": None,
            "Age": None,
            "Value": pick["val_1qb"],
            "Asset ID": None,
        })
    write_csv("rosteraudit", assign_ids("rosteraudit", rows))


if __name__ == "__main__":
    pull()
