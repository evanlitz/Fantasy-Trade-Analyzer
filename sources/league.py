import csv
import random
import sys

import requests

from common import DATA_DIR, HEADERS
from ids import sleeper_players
from trade import load_assets
from trade import raw as star

API = "https://api.sleeper.app/v1"
# Sleeper dynasty leagues trade picks for the next three drafts, which is also the span consensus.csv values
FUTURE_SEASONS = 3
TAXI_FACTOR = 0.9
VALUED_POSITIONS = {"QB", "RB", "WR", "TE"}
SLOT_ELIGIBLE = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
# Weekly chance a player is unavailable: rough per-position injury estimates (not measured) plus one bye in 17 weeks
ABSENCE = {"QB": 0.10, "RB": 0.18, "WR": 0.13, "TE": 0.13}
BYE = 1 / 17
SIM_WEEKS = 2000
WIN_NOW_WEIGHT = 0.5
# Flock Fantasy's classification: rows are win-now rank bands, columns are dynasty rank bands (top 2, top half, bottom half, bottom 2)
TIER_GRID = [
    ["Juggernaut", "Strong Contender", "All In", "All In"],
    ["Strong Contender", "Strong Contender", "Balanced", "All In"],
    ["Strong Rebuilder", "Balanced", "Purgatory", "Purgatory"],
    ["Strong Rebuilder", "Strong Rebuilder", "Purgatory", "Pip Squeak"],
]


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


def redraft_values():
    with open(DATA_DIR / "redraft.csv", encoding="utf-8") as f:
        return {r["Asset ID"]: float(r["Value"]) for r in csv.DictReader(f)}


def best_lineup(players, slots):
    # Narrowest slots first, so a flex never takes a player a dedicated slot needed
    pool = sorted(players, key=lambda p: -p["now"])
    lineup = []
    for slot in sorted(slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        pick = next((p for p in pool if p["position"] in SLOT_ELIGIBLE[slot]), None)
        if pick:
            lineup.append(pick)
            pool.remove(pick)
    return lineup


def start_shares(players, slots, seed):
    # Share of simulated weeks each player is in the best available lineup; bench players earn starts covering absences
    rng = random.Random(seed)
    starts = {p["id"]: 0 for p in players}
    for _ in range(SIM_WEEKS):
        available = [p for p in players if rng.random() > ABSENCE[p["position"]] + BYE]
        for p in best_lineup(available, slots):
            starts[p["id"]] += 1
    return {pid: n / SIM_WEEKS for pid, n in starts.items()}


def band(rank, n):
    return 0 if rank <= 2 else 3 if rank > n - 2 else 1 if rank <= n / 2 else 2


def project_tiers(rosters, win_now):
    # Draft order follows this season's finish, so average standings rank with win-now rank, weakest first.
    # Only the next draft is projected; later drafts are too far out and stay "mid".
    by_record = sorted(rosters, key=lambda r: (r["settings"]["wins"] - r["settings"]["losses"], r["settings"].get("fpts", 0)))
    by_value = sorted(rosters, key=lambda r: win_now[r["roster_id"]])
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
    top = max(a["Value"] for a in values.values())
    now_values = redraft_values()
    slots = [s for s in league["roster_positions"] if s in SLOT_ELIGIBLE]
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
                            "team": asset["Team"], "age": float(asset["Age"]) if asset["Age"] else None,
                            "raw": raw, "value": raw * TAXI_FACTOR if is_taxi else raw,
                            "now": now_values.get(pid, 0)})
        players.sort(key=lambda p: -p["value"])
        teams[r["roster_id"]] = {"roster_id": r["roster_id"], "team": names[r["roster_id"]],
                                 "record": f"{r['settings']['wins']}-{r['settings']['losses']}",
                                 "players": players, "picks": [], "unvalued": unvalued}

    win_now = {}
    for rid, t in teams.items():
        # Taxi players can't start, so they only count toward the dynasty score
        active = [p for p in t["players"] if not p["taxi"]]
        shares = start_shares(active, slots, seed=rid)
        for p in t["players"]:
            p["start"] = shares.get(p["id"], 0)
        win_now[rid] = sum(p["now"] * p["start"] for p in active)
    tiers = project_tiers(rosters, win_now)
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
        t["win_now"] = win_now[rid]
        curved = lambda p: star(p["raw"], top, top) * (TAXI_FACTOR if p["taxi"] else 1)
        # Dynasty score by asset group, star-curved so one elite player outweighs several depth pieces
        t["positions"] = {pos: sum(curved(p) for p in t["players"] if p["position"] == pos) for pos in sorted(VALUED_POSITIONS)}
        t["positions"]["PICK"] = sum(star(p["value"], top, top) for p in t["picks"])
        t["dynasty"] = sum(t["positions"].values())
        t["roster_value"] = sum(p["value"] for p in t["players"] if not p["taxi"])
        t["taxi_value"] = sum(p["value"] for p in t["players"] if p["taxi"])
        t["picks_value"] = sum(p["value"] for p in t["picks"])
        # Value-weighted, so a team's core sets its age rather than its deep bench
        aged = [p for p in t["players"] if p["age"]]
        t["age"] = sum(p["age"] * p["value"] for p in aged) / sum(p["value"] for p in aged) if aged else None
        out.append(t)

    n = len(out)
    best_now, best_dynasty = max(t["win_now"] for t in out), max(t["dynasty"] for t in out)
    now_rank = {t["roster_id"]: i for i, t in enumerate(sorted(out, key=lambda t: -t["win_now"]), 1)}
    dynasty_rank = {t["roster_id"]: i for i, t in enumerate(sorted(out, key=lambda t: -t["dynasty"]), 1)}
    for t in out:
        rid = t["roster_id"]
        t["win_now_rank"], t["dynasty_rank"] = now_rank[rid], dynasty_rank[rid]
        # Each score as a share of the league's best, blended, on a 0-100 scale
        t["overall"] = 100 * (WIN_NOW_WEIGHT * t["win_now"] / best_now + (1 - WIN_NOW_WEIGHT) * t["dynasty"] / best_dynasty)
        t["tier"] = TIER_GRID[band(now_rank[rid], n)][band(dynasty_rank[rid], n)]
    out.sort(key=lambda t: -t["overall"])
    return {"league": league["name"], "season": league["season"], "pick_seasons": seasons, "teams": out}


def report(result):
    print(f"{result['league']} ({result['season']}), picks {', '.join(result['pick_seasons'])} "
          f"({result['pick_seasons'][0]} projected, later seasons mid)\n")
    print(f"{'#':>2}  {'Team':<24}{'Tier':<18}{'Rec':>5}{'Overall':>9}{'Win-now':>12}{'Dynasty':>12}")
    for i, t in enumerate(result["teams"], 1):
        print(f"{i:>2}  {t['team'][:23]:<24}{t['tier']:<18}{t['record']:>5}{t['overall']:>9.1f}"
              f"{t['win_now']:>8,.0f} #{t['win_now_rank']:<2}{t['dynasty']:>8,.0f} #{t['dynasty_rank']:<2}")
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
