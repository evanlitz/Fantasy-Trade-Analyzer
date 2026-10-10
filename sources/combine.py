import csv
import math
from bisect import bisect_right
from collections import Counter
from statistics import median

from common import DATA_DIR

# Metadata (name, age) comes from the first source listing an asset, so the most precise go first
SOURCES = ["ktc", "rosteraudit", "dynastyprocess", "fantasycalc", "dynastydealer", "dynastydaddy", "draftsharks", "fantasypros"]
MIN_SOURCES = 3
COLUMNS = ["Player Name", "Type", "Position", "Team", "Age", "Value", "Asset ID", "Sources", "Low", "High"] + SOURCES


def curve(rank):
    # KTC-shaped (fit to ktc.csv: 0.081/0.52; FantasyCalc+Dynasty Dealer+KTC: 0.077/0.54). Deliberately flat:
    # the trade evaluator's KTC value adjustment is tuned to this shape and supplies the stud premium.
    return 10000 * math.exp(-0.08 * (rank - 1) ** 0.53)


def player_ranks(values):
    # values sorted descending; tied values share the average of their positions
    ranks, i = [], 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[i]:
            j += 1
        ranks += [(i + j) / 2 + 1] * (j - i + 1)
        i = j + 1
    return ranks


def equivalent_rank(value, player_values):
    # Where a pick's value would sit among this source's players, interpolated between neighbours
    neg = [-v for v in player_values]
    i = bisect_right(neg, -value)  # players worth >= value
    if i == 0:
        return 1.0
    if i == len(player_values):
        return float(len(player_values))
    above, below = player_values[i - 1], player_values[i]
    return i + (above - value) / (above - below)


def load(source):
    with open(DATA_DIR / f"{source}.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["Value"] = float(r["Value"])
    players = sorted((r for r in rows if r["Type"] == "Player"), key=lambda r: -r["Value"])
    player_values = [r["Value"] for r in players]
    for r, rank in zip(players, player_ranks(player_values)):
        r["Rank"] = rank
    for r in rows:
        if r["Type"] == "Pick":
            r["Rank"] = equivalent_rank(r["Value"], player_values)
    return rows


def combine():
    assets = {}
    for source in SOURCES:
        for r in load(source):
            asset = assets.setdefault(r["Asset ID"], {"meta": r, "teams": Counter(), "values": {}})
            asset["values"][source] = curve(r["Rank"])
            if r["Type"] == "Player":
                asset["teams"][r["Team"]] += 1

    out = []
    for asset_id, a in assets.items():
        if len(a["values"]) < MIN_SOURCES:
            continue
        m, vals = a["meta"], a["values"].values()
        out.append({
            "Player Name": m["Player Name"],
            "Type": m["Type"],
            "Position": m["Position"],
            # FantasyCalc lags on team changes, so take the team most sources agree on
            "Team": a["teams"].most_common(1)[0][0] if a["teams"] else "",
            "Age": m["Age"],
            "Value": round(median(vals)),
            "Asset ID": asset_id,
            "Sources": len(vals),
            "Low": round(min(vals)),
            "High": round(max(vals)),
            **{s: round(v) for s, v in a["values"].items()},
        })
    out.sort(key=lambda r: -r["Value"])

    path = DATA_DIR / "consensus.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out)
    dropped = sum(len(a["values"]) < MIN_SOURCES for a in assets.values())
    print(f"consensus: {len(out)} assets ({sum(r['Type'] == 'Pick' for r in out)} picks), {dropped} dropped under {MIN_SOURCES} sources -> {path}")


if __name__ == "__main__":
    combine()
