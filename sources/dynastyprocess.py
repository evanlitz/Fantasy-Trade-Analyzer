import csv
import io
from datetime import date

import requests

from common import HEADERS, write_csv
from ids import assign_ids, sleeper_id_from

URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values.csv"


def pull():
    text = requests.get(URL, headers=HEADERS, timeout=60).text
    # DP keeps pick rows for drafts that already happened; the NFL draft is in late April
    today = date.today()
    next_draft_year = today.year if today.month < 5 else today.year + 1

    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        is_pick = r["pos"] == "PICK"
        if is_pick and int(r["player"][:4]) < next_draft_year:
            continue
        rows.append({
            "Player Name": r["player"],
            "Type": "Pick" if is_pick else "Player",
            "Position": r["pos"],
            "Team": None if r["team"] == "NA" else r["team"],
            "Age": None if r["age"] == "NA" else float(r["age"]),
            "Value": int(r["value_1qb"]),
            "Asset ID": None if is_pick else sleeper_id_from("fantasypros_id", r["fp_id"]),
        })
    write_csv("dynastyprocess", assign_ids("dynastyprocess", rows))


if __name__ == "__main__":
    pull()
