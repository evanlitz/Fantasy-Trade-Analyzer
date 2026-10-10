import requests

from common import HEADERS, write_csv
from ids import assign_ids

BASE = "https://api.dynasty-daddy.com/api/v1/player/all"
# Market ids from the dynasty-daddy.com frontend bundle. KTC, FantasyCalc, DynastyProcess
# and RosterAudit are pulled from their own APIs instead; ProFootballNetwork (9) and
# Fantasy Navigator (3, "DynastySuperflex" internally) are stale; DD ADP (6) was dropped.
MARKETS = {
    14: "dynastydaddy",
    12: "draftsharks",
}


def pull():
    meta = {p["name_id"]: p for p in requests.get(f"{BASE}/today", headers=HEADERS, timeout=60).json()}
    for market_id, source in MARKETS.items():
        values = requests.get(f"{BASE}/market/{market_id}", headers=HEADERS, timeout=60).json()
        rows = []
        for v in values:
            p = meta.get(v["name_id"])
            if not p or not v["trade_value"]:
                continue
            is_pick = p["position"] == "PI"
            rows.append({
                "Player Name": p["full_name"],
                "Type": "Pick" if is_pick else "Player",
                "Position": "PICK" if is_pick else p["position"],
                "Team": None if is_pick else p["team"],
                "Age": None if is_pick else p["age"],
                "Value": v["trade_value"],
                "Asset ID": p["sleeper_id"],
            })
        write_csv(source, assign_ids(source, rows))


if __name__ == "__main__":
    pull()
