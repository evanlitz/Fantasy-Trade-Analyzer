import json

import requests
from bs4 import BeautifulSoup

from common import HEADERS, write_csv
from ids import assign_ids, sleeper_id_from

# Every rankings page embeds the full 500-asset list as JSON, so one request covers it all
URL = "https://keeptradecut.com/dynasty-rankings?page=0&filters=QB|WR|RB|TE|RDP&format=1"
# KTC's "Crowd+Trades" value: the average of Crowdsourced (value) and Tradesourced (vftValue)
VALUE_FIELD = "blendValue"


def pull():
    soup = BeautifulSoup(requests.get(URL, headers=HEADERS, timeout=60).content, "html.parser")
    players = json.loads(soup.find(id="ktc-players").get_text())
    rows = []
    for p in players:
        is_pick = p["position"] == "RDP"
        rows.append({
            "Player Name": p["playerName"],
            "Type": "Pick" if is_pick else "Player",
            "Position": "PICK" if is_pick else p["position"],
            "Team": None if is_pick else p["team"],
            "Age": None if is_pick else p["age"],
            "Value": p["oneQBValues"][VALUE_FIELD],
            "Asset ID": None if is_pick else sleeper_id_from("mfl_id", p.get("mflid")) or sleeper_id_from("ktc_id", p["playerID"]),
        })
    write_csv("ktc", assign_ids("ktc", rows))


if __name__ == "__main__":
    pull()
