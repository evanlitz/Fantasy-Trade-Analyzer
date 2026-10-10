import requests

from common import HEADERS, write_csv
from ids import assign_ids

URL = "https://www.dynastydealer.com/api/player-values"
# The API only serves superflex + TE premium values and ignores its isSuperflex/isTePremium params.
# The site's 1QB rankings apply these multipliers client-side (adjustPlayerValue in main.js); picks are unchanged.
MULTIPLIERS = {"QB": 0.66, "TE": 0.89}
POSITIONS = {"QB", "RB", "WR", "TE", "PICK"}


def pull():
    data = requests.get(URL, params={"perSlot": "true"}, headers=HEADERS, timeout=60).json()
    rows = []
    for p in data["players"]:
        if p["position"] not in POSITIONS or not p["current_value"]:
            continue
        is_pick = p["position"] == "PICK"
        rows.append({
            "Player Name": p["name"],
            "Type": "Pick" if is_pick else "Player",
            "Position": p["position"],
            "Team": None if is_pick else p["team"],
            "Age": None if is_pick else p["age"],
            "Value": round(p["current_value"] * MULTIPLIERS.get(p["position"], 1)),
            "Asset ID": None if is_pick else p["sleeper_id"],
        })
    write_csv("dynastydealer", assign_ids("dynastydealer", rows))


if __name__ == "__main__":
    pull()
