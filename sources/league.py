import sys

import requests

from common import HEADERS
from ids import sleeper_players
from trade import load_assets

API = "https://api.sleeper.app/v1"
# Sleeper dynasty leagues trade picks for the next three drafts, which is also the span consensus.csv values
FUTURE_SEASONS = 3
TAXI_FACTOR = 0.9
VALUED_POSITIONS = {"QB", "RB", "WR", "TE"}


def get(path):
    response = requests.get(API + path, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def team_name(roster, users):
    user = users.get(roster["owner_id"]) or {}
    name = (user.get("metadata") or {}).get("team_name") or user.get("display_name") or f"Team {roster['roster_id']}"
    return name.strip()


def pick_seasons(league, drafts):
    season = int(league["season"])
    done = any(d["season"] == league["season"] and d["status"] == "complete" for d in drafts)
    first = season + 1 if done else season
    return [str(s) for s in range(first, first + FUTURE_SEASONS)]


def project_tiers(rosters, player_value):
    # Mid-season projection: average each team's standings rank with its roster-value rank, weakest first.
    # Only the next draft is projected; later drafts are too far out and stay "mid".
    by_record = sorted(rosters, key=lambda r: (r["settings"]["wins"] - r["settings"]["losses"], r["settings"].get("fpts", 0)))
    by_value = sorted(rosters, key=lambda r: player_value[r["roster_id"]])
    rank = {r["roster_id"]: by_record.index(r) + by_value.index(r) for r in rosters}
    order = sorted(rosters, key=lambda r: rank[r["roster_id"]])
    third = round(len(order) / 3)
    return {r["roster_id"]: "early" if i < third else "late" if i >= len(order) - third else "mid"
            for i, r in enumerate(order)}


def league_values(league_id):
    league = get(f"/league/{league_id}")
    users = {u["user_id"]: u for u in get(f"/league/{league_id}/users")}
    rosters = get(f"/league/{league_id}/rosters")
    traded = get(f"/league/{league_id}/traded_picks")
    drafts = get(f"/league/{league_id}/drafts")
    values = {a["Asset ID"]: a for a in load_assets()}
    sleeper = sleeper_players()
    names = {r["roster_id"]: team_name(r, users) for r in rosters}

    teams = {}
    for r in rosters:
        taxi = set(r["taxi"] or [])
        players, unvalued = [], []
        for pid in r["players"] or []:
            is_taxi = pid in taxi
            asset = values.get(pid)
            info = sleeper.get(pid, {})
            position = info.get("position") or pid
            if not asset:
                if position in VALUED_POSITIONS:
                    unvalued.append({"id": pid, "name": info.get("full_name", pid), "position": position, "taxi": is_taxi})
                continue
            raw = asset["Value"]
            players.append({"id": pid, "name": asset["Player Name"], "position": asset["Position"], "taxi": is_taxi,
                            "raw": raw, "value": raw * TAXI_FACTOR if is_taxi else raw})
        players.sort(key=lambda p: -p["value"])
        teams[r["roster_id"]] = {"roster_id": r["roster_id"], "team": names[r["roster_id"]],
                                 "record": f"{r['settings']['wins']}-{r['settings']['losses']}",
                                 "players": players, "picks": [], "unvalued": unvalued}

    player_value = {rid: sum(p["value"] for p in t["players"]) for rid, t in teams.items()}
    tiers = project_tiers(rosters, player_value)
    seasons = pick_seasons(league, drafts)
    owner = {(s, rnd, r["roster_id"]): r["roster_id"]
             for s in seasons for rnd in range(1, league["settings"]["draft_rounds"] + 1) for r in rosters}
    for p in traded:
        key = (p["season"], p["round"], p["roster_id"])
        if key in owner:
            owner[key] = p["owner_id"]
    for (season, rnd, original), current in sorted(owner.items()):
        tier = tiers[original] if season == seasons[0] else "mid"
        asset = values.get(f"{season}-{rnd}-{tier}")
        teams[current]["picks"].append({
            "season": season, "round": rnd, "tier": tier, "projected": season == seasons[0],
            "from": None if original == current else names[original],
            "value": asset["Value"] if asset else 0,
        })

    out = []
    for rid, t in teams.items():
        t["roster_value"] = sum(p["value"] for p in t["players"] if not p["taxi"])
        t["taxi_value"] = sum(p["value"] for p in t["players"] if p["taxi"])
        t["picks_value"] = sum(p["value"] for p in t["picks"])
        t["total"] = player_value[rid] + t["picks_value"]
        out.append(t)
    out.sort(key=lambda t: -t["total"])
    return {"league": league["name"], "season": league["season"], "pick_seasons": seasons, "teams": out}


def report(result):
    print(f"{result['league']} ({result['season']}), picks {', '.join(result['pick_seasons'])} "
          f"({result['pick_seasons'][0]} projected, later seasons mid)\n")
    print(f"{'#':>2}  {'Team':<24}{'Rec':>5}{'Total':>9}{'Roster':>9}{'Taxi':>8}{'Picks':>8}")
    for i, t in enumerate(result["teams"], 1):
        print(f"{i:>2}  {t['team'][:23]:<24}{t['record']:>5}{t['total']:>9,.0f}{t['roster_value']:>9,.0f}"
              f"{t['taxi_value']:>8,.0f}{t['picks_value']:>8,.0f}")
    print()
    for t in result["teams"]:
        picks = ", ".join(f"{p['season'][2:]} R{p['round']} {p['tier']}" + (f" (from {p['from']})" if p["from"] else "")
                          for p in t["picks"])
        print(f"{t['team']}: {picks or 'no picks'}")
        if t["unvalued"]:
            print(f"  no value: {', '.join(p['name'] + ' ' + p['position'] for p in t['unvalued'])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    report(league_values(sys.argv[1]))
