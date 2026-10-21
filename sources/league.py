import csv
import random
import sys

from common import DATA_DIR, sleeper_get
from ids import sleeper_players
from trade import find, load_assets, verdict
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
# A trade's start-share changes smaller than this aren't worth listing
START_CHANGE = 0.10
# Free agents re-scored onto a roster: the top this many by dynasty value plus the top this many by win-now value
FA_POOL = 25
# Flock Fantasy's classification: rows are win-now rank bands, columns are dynasty rank bands (top 2, top half, bottom half, bottom 2)
TIER_GRID = [
    ["Juggernaut", "Strong Contender", "All In", "All In"],
    ["Strong Contender", "Strong Contender", "Balanced", "All In"],
    ["Strong Rebuilder", "Balanced", "Purgatory", "Purgatory"],
    ["Strong Rebuilder", "Strong Rebuilder", "Purgatory", "Pip Squeak"],
]


def get(path):
    return sleeper_get(API + path).json()


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


def lineup_slots(players, slots):
    # Same picks as best_lineup, kept in the league's slot order with each slot named, for display
    pool = sorted(players, key=lambda p: -p["now"])
    filled = {}
    for i in sorted(range(len(slots)), key=lambda i: len(SLOT_ELIGIBLE[slots[i]])):
        pick = next((p for p in pool if p["position"] in SLOT_ELIGIBLE[slots[i]]), None)
        if pick:
            filled[i] = pick
            pool.remove(pick)
    return [{"slot": slot, "id": filled[i]["id"] if i in filled else None} for i, slot in enumerate(slots)]


def absences(pid, position):
    # Seeded by the player's own ID, so a player misses the same simulated weeks on any roster and a trade's
    # before/after difference is the trade, not simulation noise
    rng = random.Random(f"absence-{pid}")
    miss = ABSENCE[position] + BYE
    return [rng.random() < miss for _ in range(SIM_WEEKS)]


def start_shares(players, slots, absent):
    # Share of simulated weeks each player is in the best available lineup; bench players earn starts covering absences
    starts = {p["id"]: 0 for p in players}
    for week in range(SIM_WEEKS):
        available = [p for p in players if not absent[p["id"]][week]]
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


def fetch(league_id):
    return {
        "league": get(f"/league/{league_id}"),
        "users": get(f"/league/{league_id}/users"),
        "rosters": get(f"/league/{league_id}/rosters"),
        "traded": get(f"/league/{league_id}/traded_picks"),
        "drafts": get(f"/league/{league_id}/drafts"),
    }


class League:
    # Rosters are built once from Sleeper; score() values any version of them, so a trade is the same rosters with
    # assets moved, scored again

    def __init__(self, raw, assets, now_values, sleeper):
        league = raw["league"]
        users = {u["user_id"]: u for u in raw["users"]}
        self.league = league
        self.raw_rosters = raw["rosters"]
        self.values = {a["Asset ID"]: a for a in assets}
        self.top = max(a["Value"] for a in assets)
        self.now_values = now_values
        self.sleeper = sleeper
        self.taken = {pid for r in raw["rosters"] for pid in r["players"] or []}
        self.slots = [s for s in league["roster_positions"] if s in SLOT_ELIGIBLE]
        # Starters plus bench; taxi and IR don't count against it
        self.roster_limit = len(league["roster_positions"])
        self.names = {r["roster_id"]: team_name(r, users) for r in raw["rosters"]}
        self.records = {r["roster_id"]: f"{r['settings']['wins']}-{r['settings']['losses']}" for r in raw["rosters"]}
        self.seasons = pick_seasons(league, raw["drafts"])
        self.absent = {}
        self.shares_memo = {}

        self.rosters = {}
        for r in raw["rosters"]:
            taxi, reserve = set(r.get("taxi") or []), set(r.get("reserve") or [])
            players, unvalued = [], []
            for pid in r["players"] or []:
                asset = self.values.get(pid)
                info = sleeper.get(pid, {})
                position = info.get("position") or pid
                flags = {"taxi": pid in taxi, "reserve": pid in reserve}
                if not asset:
                    if position in VALUED_POSITIONS:
                        unvalued.append({"id": pid, "name": info.get("full_name", pid), "position": position, **flags})
                    continue
                players.append({"id": pid, "name": asset["Player Name"], "position": asset["Position"], **flags,
                                "team": asset["Team"], "age": float(asset["Age"]) if asset["Age"] else None,
                                "raw": asset["Value"], "now": now_values.get(pid, 0)})
            spots = sum(1 for pid in r["players"] or [] if pid not in taxi and pid not in reserve)
            self.rosters[r["roster_id"]] = {"players": players, "picks": [], "unvalued": unvalued, "spots": spots}

        owner = {(s, rnd, r["roster_id"]): r["roster_id"]
                 for s in self.seasons for rnd in range(1, league["settings"]["draft_rounds"] + 1) for r in raw["rosters"]}
        for p in raw["traded"]:
            key = (p["season"], p["round"], p["roster_id"])
            if key in owner:
                owner[key] = p["owner_id"]
        for (season, rnd, original), current in sorted(owner.items()):
            self.rosters[current]["picks"].append(
                {"id": f"{season}-{rnd}-r{original}", "season": season, "round": rnd, "original": original})

        self.base = self.score(self.rosters)
        # Every tradeable asset: a player by Sleeper ID, a pick by season, round and original roster
        self.owner = {a["id"]: rid for rid, t in self.rosters.items() for a in t["players"] + t["picks"]}

    @classmethod
    def load(cls, league_id):
        return cls(fetch(league_id), load_assets(), redraft_values(), sleeper_players())

    def shares(self, active):
        key = frozenset(p["id"] for p in active)
        if key not in self.shares_memo:
            for p in active:
                if p["id"] not in self.absent:
                    self.absent[p["id"]] = absences(p["id"], p["position"])
            self.shares_memo[key] = start_shares(active, self.slots, self.absent)
        return self.shares_memo[key]

    def score(self, rosters):
        teams = {}
        for rid, r in rosters.items():
            players = [{**p, "value": p["raw"] * TAXI_FACTOR if p["taxi"] else p["raw"]} for p in r["players"]]
            players.sort(key=lambda p: -p["value"])
            teams[rid] = {"roster_id": rid, "team": self.names[rid],
                          "record": self.records[rid],
                          "players": players, "picks": [], "unvalued": r["unvalued"]}

        win_now = {}
        for rid, t in teams.items():
            # Taxi players can't start, so they only count toward the dynasty score
            active = [p for p in t["players"] if not p["taxi"]]
            shares = self.shares(active)
            for p in t["players"]:
                p["start"] = shares.get(p["id"], 0)
            win_now[rid] = sum(p["now"] * p["start"] for p in active)
            t["lineup"] = lineup_slots(active, self.slots)
        tiers = project_tiers(self.raw_rosters, win_now)
        for rid, r in rosters.items():
            for p in r["picks"]:
                projected = p["season"] == self.seasons[0]
                tier = tiers[p["original"]] if projected else "mid"
                asset = self.values.get(f"{p['season']}-{p['round']}-{tier}")
                teams[rid]["picks"].append({**p, "tier": tier, "projected": projected,
                                            "from": None if p["original"] == rid else self.names[p["original"]],
                                            "value": asset["Value"] if asset else 0})

        out = []
        for rid, t in teams.items():
            t["win_now"] = win_now[rid]
            curved = lambda p: star(p["raw"], self.top, self.top) * (TAXI_FACTOR if p["taxi"] else 1)
            # Dynasty score by asset group, star-curved so one elite player outweighs several depth pieces
            t["positions"] = {pos: sum(curved(p) for p in t["players"] if p["position"] == pos)
                              for pos in sorted(VALUED_POSITIONS)}
            t["positions"]["PICK"] = sum(star(p["value"], self.top, self.top) for p in t["picks"])
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
            t["overall"] = 100 * (WIN_NOW_WEIGHT * t["win_now"] / best_now
                                  + (1 - WIN_NOW_WEIGHT) * t["dynasty"] / best_dynasty)
            t["tier"] = TIER_GRID[band(now_rank[rid], n)][band(dynasty_rank[rid], n)]
        out.sort(key=lambda t: -t["overall"])
        for i, t in enumerate(out, 1):
            t["overall_rank"] = i
        return {"league": self.league["name"], "season": self.league["season"], "pick_seasons": self.seasons,
                "draft_rounds": self.league["settings"]["draft_rounds"], "teams": out}

    def team(self, result, rid):
        return next(t for t in result["teams"] if t["roster_id"] == rid)

    def market(self, asset_id):
        # What the trade calculator prices an asset at: consensus value, picks at their pre-trade projected tier
        rid = self.owner[asset_id]
        t = self.team(self.base, rid)
        p = next(x for x in t["players"] + t["picks"] if x["id"] == asset_id)
        if "season" in p:
            return {"Asset ID": asset_id, "Player Name": f"{p['season']} R{p['round']} {p['tier']}"
                    + (f" (from {p['from']})" if p["from"] else ""), "Type": "Pick", "Position": "PICK",
                    "Team": "", "Value": p["value"]}
        return {"Asset ID": asset_id, "Player Name": p["name"], "Type": "Player", "Position": p["position"],
                "Team": p["team"], "Value": p["raw"]}

    def side_owner(self, ids, label):
        if not ids:
            raise ValueError(f"Side {label} is empty")
        missing = [i for i in ids if i not in self.owner]
        if missing:
            raise ValueError(f"Side {label}: {', '.join(missing)} not on any roster (or has no consensus value)")
        owners = {self.owner[i] for i in ids}
        if len(owners) > 1:
            raise ValueError(f"Side {label} has assets from {len(owners)} teams; each side is one team")
        return owners.pop()

    def after_trade(self, ra, a_ids, rb, b_ids):
        rosters = dict(self.rosters)
        for rid, out_ids, other, in_ids in ((ra, a_ids, rb, b_ids), (rb, b_ids, ra, a_ids)):
            mine, theirs = self.rosters[rid], self.rosters[other]
            leaving = [p for p in mine["players"] if p["id"] in out_ids]
            # Received players arrive on the bench, off taxi and IR
            arriving = [{**p, "taxi": False, "reserve": False} for p in theirs["players"] if p["id"] in in_ids]
            players = [p for p in mine["players"] if p["id"] not in out_ids] + arriving
            unvalued = list(mine["unvalued"])
            spots = mine["spots"] - sum(not p["taxi"] and not p["reserve"] for p in leaving) + len(arriving)
            # Over the roster limit, the cheapest players are assumed cut: unvalued ones first, then by value.
            # A team already over the limit (offseason) only cuts what the trade adds.
            cuts = max(0, spots - max(self.roster_limit, mine["spots"]))
            droppable = lambda p: not p["taxi"] and not p["reserve"]
            for _ in range(cuts):
                spare = [p for p in unvalued if droppable(p)]
                if spare:
                    unvalued.remove(spare[0])
                else:
                    players.remove(min((p for p in players if droppable(p)), key=lambda p: p["raw"]))
            picks = [p for p in mine["picks"] if p["id"] not in out_ids] + \
                    [p for p in theirs["picks"] if p["id"] in in_ids]
            rosters[rid] = {"players": players, "picks": picks, "unvalued": unvalued,
                            "spots": spots - cuts, "cuts": cuts}
        return rosters

    def trade(self, a_ids, b_ids):
        a_ids, b_ids = list(dict.fromkeys(a_ids)), list(dict.fromkeys(b_ids))
        if set(a_ids) & set(b_ids):
            raise ValueError("An asset can't be on both sides")
        ra, rb = self.side_owner(a_ids, "A"), self.side_owner(b_ids, "B")
        if ra == rb:
            raise ValueError("Both sides are the same team")

        # Fairness is the trade calculator's market verdict; evening suggestions come from the losing team's roster
        own = lambda rid: [self.market(i) for i, r in self.owner.items() if r == rid]
        fair = verdict([self.market(i) for i in a_ids], [self.market(i) for i in b_ids], self.top, own(ra), own(rb))

        rosters = self.after_trade(ra, set(a_ids), rb, set(b_ids))
        after = self.score(rosters)
        return {**fair, "teams": {"a": self.impact(ra, rb, after, rosters), "b": self.impact(rb, ra, after, rosters)}}

    def impact(self, rid, other, after, rosters):
        fields = ["win_now", "win_now_rank", "dynasty", "dynasty_rank", "overall", "overall_rank", "tier", "age"]
        snap = lambda t: {**{f: t[f] for f in fields}, "positions": t["positions"]}
        before_t, after_t = self.team(self.base, rid), self.team(after, rid)

        # Start share before (on whichever team had the player) and after: every arrival, plus players already
        # here whose share moved enough to matter
        before_starts = {p["id"]: p["start"] for r in (rid, other) for p in self.team(self.base, r)["players"]}
        had = {p["id"] for p in before_t["players"]}
        starts = [{"id": p["id"], "name": p["name"], "position": p["position"],
                   "before": before_starts[p["id"]], "after": p["start"], "arrived": p["id"] not in had}
                  for p in after_t["players"]
                  if p["id"] not in had or abs(p["start"] - before_starts[p["id"]]) >= START_CHANGE]
        starts.sort(key=lambda s: (not s["arrived"], -abs(s["after"] - s["before"])))

        # Next draft's picks this team holds whose projected tier moved because win-now scores moved
        before_tiers = {p["id"]: p["tier"] for r in (rid, other) for p in self.team(self.base, r)["picks"]}
        picks = [{"id": p["id"], "season": p["season"], "round": p["round"], "from": p["from"],
                  "before": before_tiers[p["id"]], "after": p["tier"]}
                 for p in after_t["picks"] if p["tier"] != before_tiers[p["id"]]]

        return {"roster_id": rid, "team": self.names[rid], "before": snap(before_t), "after": snap(after_t),
                "starts": starts, "pick_tiers": picks, "cuts": rosters[rid]["cuts"]}

    def free_agent_pool(self):
        pool = []
        for pid in set(self.values) | set(self.now_values):
            if pid in self.taken:
                continue
            asset, info = self.values.get(pid), self.sleeper.get(pid, {})
            position = asset["Position"] if asset else info.get("position")
            # Redraft-only players need an NFL team; that filters out retired and unsigned names
            if position not in VALUED_POSITIONS or not (asset or info.get("team")):
                continue
            age = (asset["Age"] if asset else info.get("age")) or None
            pool.append({"id": pid, "name": asset["Player Name"] if asset else info.get("full_name", pid),
                         "position": position, "team": asset["Team"] if asset else info.get("team"),
                         "age": float(age) if age else None, "taxi": False, "reserve": False,
                         "raw": asset["Value"] if asset else 0, "now": self.now_values.get(pid, 0)})
        top = lambda key: sorted(pool, key=lambda p: -p[key])[:FA_POOL]
        return list({p["id"]: p for p in top("raw") + top("now")}.values())

    def free_agents(self, rid):
        # Each free agent added to this team, dropping drop_candidate() when the roster is full, then re-scored.
        # The drop doesn't depend on the free agent, so it's one per team.
        before = self.team(self.base, rid)
        mine = self.rosters[rid]
        full = mine["spots"] >= self.roster_limit
        droppable = [p for p in before["players"] if not p["taxi"] and not p["reserve"]]
        drop = drop_candidate(droppable, mine["unvalued"]) if full else None
        gone = drop["id"] if drop else None
        out = []
        for fa in self.free_agent_pool():
            rosters = {**self.rosters, rid: {**mine, "players": [p for p in mine["players"] if p["id"] != gone] + [fa],
                                             "unvalued": [p for p in mine["unvalued"] if p["id"] != gone]}}
            after = self.team(self.score(rosters), rid)
            out.append({
                **{k: fa[k] for k in ("id", "name", "position", "team", "age", "now")}, "value": fa["raw"],
                "start": next(p["start"] for p in after["players"] if p["id"] == fa["id"]),
                **{f"{k}_change": after[k] - before[k] for k in ("win_now", "dynasty", "overall")},
                "tier": after["tier"],
            })
        out.sort(key=lambda f: -f["value"])
        return {"team": self.names[rid], "roster_id": rid, "tier": before["tier"], "record": self.records[rid],
                "spots": mine["spots"], "limit": self.roster_limit, "full": full,
                "drop": drop and {"id": drop["id"], "name": drop["name"], "position": drop["position"],
                                  "value": drop.get("raw", 0), "now": drop.get("now", 0), "start": drop.get("start", 0)},
                "free_agents": out}

    def find(self, query):
        # CLI lookup: player name or any league asset ID, restricted to assets on a roster
        return find(query, [self.market(i) for i in self.owner])["Asset ID"]


def drop_candidate(players, unvalued):
    # Lowest consensus value goes; players no source values count as zero, so they go first
    spare = [p for p in unvalued if not p["taxi"] and not p["reserve"]]
    if spare:
        return spare[0]
    return min(players, key=lambda p: p["raw"])


def league_values(league_id):
    return League.load(league_id).base


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


def trade_report(result):
    for label in ("a", "b"):
        gives = ", ".join(f"{r['Player Name']} ({r['Value']:,.0f})" for r in result["side_" + label])
        print(f"{result['teams'][label]['team']} gives: {gives}")
    # Each side is what that team gives, so the "winning" side is the team giving more
    giver = result["teams"][result["winner"].lower()]["team"]
    taker = result["teams"]["b" if result["winner"] == "A" else "a"]["team"]
    verdict_text = "fair" if result["fair"] else f"{giver} gives {result['margin']:,.0f} more"
    if result["suggestions"]:
        verdict_text += f"; {taker} could add " + ", ".join(r["Player Name"] for r in result["suggestions"])
    print("Market: " + verdict_text)
    for label in ("a", "b"):
        t = result["teams"][label]
        b, a = t["before"], t["after"]
        print(f"\n{t['team']}: {b['tier']} -> {a['tier']}, overall {b['overall']:.1f} -> {a['overall']:.1f}")
        print(f"  win-now {b['win_now']:,.0f} #{b['win_now_rank']} -> {a['win_now']:,.0f} #{a['win_now_rank']} "
              f"({a['win_now'] - b['win_now']:+,.0f})")
        print(f"  dynasty {b['dynasty']:,.0f} #{b['dynasty_rank']} -> {a['dynasty']:,.0f} #{a['dynasty_rank']} "
              f"({a['dynasty'] - b['dynasty']:+,.0f})")
        print("  by position: " + ", ".join(f"{pos} {a['positions'][pos] - b['positions'][pos]:+,.0f}"
                                             for pos in b["positions"] if round(a["positions"][pos] - b["positions"][pos])))
        for s in t["starts"]:
            print(f"  {s['name']} {s['position']}: starts {s['before']:.0%} -> {s['after']:.0%}")
        for p in t["pick_tiers"]:
            print(f"  {p['season']} R{p['round']}" + (f" (from {p['from']})" if p["from"] else "")
                  + f": projects {p['before']} -> {p['after']}")


def free_agent_report(result):
    d = result["drop"]
    print(f"Free agents for {result['team']} ({result['tier']}), {result['spots']}/{result['limit']}"
          + (f", drops {d['name']} ({d['value']:,})" if d else "") + "\n")
    print(f"{'Player':<26}{'Pos':<5}{'Value':>6}{'Now':>7}{'Starts':>8}{'Win-now':>9}{'Dynasty':>9}")
    for f in result["free_agents"]:
        print(f"{f['name'][:25]:<26}{f['position']:<5}{f['value']:>6,}{f['now']:>7,.0f}{f['start']:>8.0%}"
              f"{f['win_now_change']:>+9,.0f}{f['dynasty_change']:>+9,.0f}")


if __name__ == "__main__":
    # python league.py <league_id>                              league report
    # python league.py <league_id> "Jahmyr Gibbs" vs "Garrett Wilson, 2027-1-r4"   trade impact
    # python league.py <league_id> --fa <roster id>              free agents for that team
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) == 2:
        report(league_values(sys.argv[1]))
    elif sys.argv[2] == "--fa":
        free_agent_report(League.load(sys.argv[1]).free_agents(int(sys.argv[3])))
    else:
        lg = League.load(sys.argv[1])
        a, _, b = " ".join(sys.argv[2:]).partition(" vs ")
        try:
            trade_report(lg.trade([lg.find(q) for q in a.split(",") if q.strip()],
                                  [lg.find(q) for q in b.split(",") if q.strip()]))
        except ValueError as e:
            sys.exit(str(e))
