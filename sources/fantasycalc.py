import requests

from common import HEADERS, write_csv
from ids import assign_ids

URL = "https://api.fantasycalc.com/values/current"
PARAMS = {"isDynasty": "true", "numQbs": 1, "numTeams": 12, "ppr": 1}


def pull():
    data = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=60).json()
    rows = []
    for entry in data:
        player = entry["player"]
        is_pick = player["position"] == "PICK"
        rows.append({
            "Player Name": player["name"],
            "Type": "Pick" if is_pick else "Player",
            "Position": player["position"],
            "Team": player["maybeTeam"],
            "Age": player["maybeAge"],
            "Value": entry["value"],
            # picks carry synthetic ids like FP_2027_early_0
            "Asset ID": None if is_pick else player["sleeperId"],
        })
    write_csv("fantasycalc", assign_ids("fantasycalc", rows))


if __name__ == "__main__":
    pull()
