import requests

from common import HEADERS, write_csv
from ids import assign_ids

# Current-season (redraft) values for the league analyzer's win-now score, not for dynasty consensus.
# Unlike its dynasty values, Dynasty Dealer's redraft mode honours sf=false (1QB) and the scoring format.
URL = "https://www.dynastydealer.com/api/player-values"
PARAMS = {"format": "redraft", "scoring": "ppr", "sf": "false"}
POSITIONS = {"QB", "RB", "WR", "TE"}


def pull():
    data = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=60).json()
    rows = []
    for p in data["players"]:
        if p["position"] not in POSITIONS or not p["current_value"]:
            continue
        rows.append({
            "Player Name": p["name"],
            "Type": "Player",
            "Position": p["position"],
            "Team": p["team"],
            "Age": p["age"],
            "Value": p["current_value"],
            "Asset ID": p["sleeper_id"],
        })
    write_csv("redraft", assign_ids("redraft", rows))


if __name__ == "__main__":
    pull()
