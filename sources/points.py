import csv
import io
import sys
from datetime import date

import requests

from common import DATA_DIR, HEADERS, normalize_team, sleeper_get
from ids import sleeper_id_from, sleeper_players
from league import get

# Undocumented (the host Sleeper's own app uses); api.sleeper.app/v1/projections went empty in 2026
STATS_API = "https://api.sleeper.com"
NFLVERSE_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
POSITIONS = ["QB", "RB", "WR", "TE"]
PATH = DATA_DIR / "points.csv"
COLUMNS = ["Player Name", "Position", "Team", "Asset ID", "Week", "Last Week", "Projected Week", "Rest of Season",
           "Scraped At"]
LAST_WEEK = 18
# Raw counts both sources should agree on exactly. Points can't be compared: Sleeper's pts_ppr and nflverse's
# fantasy_points_ppr each score interceptions, return fumbles and special teams plays differently
COMPARED = {
    "pass_yd": "passing_yards", "pass_td": "passing_tds", "pass_int": "passing_interceptions",
    "rush_yd": "rushing_yards", "rush_td": "rushing_tds",
    "rec": "receptions", "rec_yd": "receiving_yards", "rec_td": "receiving_tds",
    "fum_lost": "fumbles_lost_total",
}
MAX_SHARE = 0.10


def score(stats, scoring):
    # Sleeper's stat keys are the league's scoring keys, so league points are a dot product. The pts_* totals and
    # ranks in the same object are never scoring keys, so they drop out
    return round(sum(v * scoring[k] for k, v in stats.items() if k in scoring), 2)


def stat_lines(kind, season, week=None):
    path = f"/{kind}/nfl/{season}" + (f"/{week}" if week else "")
    rows = sleeper_get(STATS_API + path, params={"season_type": "regular", "position[]": POSITIONS}, timeout=60).json()
    return {r["player_id"]: r for r in rows}


def pull(league_id):
    state = get("/state/nfl")
    if state["season_type"] != "regular":
        print(f"points: skipped, Sleeper is in the {state['season_type']} season")
        return
    season, week = state["season"], state["week"]
    scoring = get(f"/league/{league_id}")["scoring_settings"]
    last = stat_lines("stats", season, week - 1) if week > 1 else {}
    # Sleeper's season projection is a full 18-game total that still counts weeks already played, so rest of
    # season is summed from each remaining week's projection. Bye weeks still get a row, with no opponent and only
    # an ADP placeholder in stats
    weekly = [{pid: r for pid, r in stat_lines("projections", season, w).items() if r.get("opponent")}
              for w in range(week, LAST_WEEK + 1)]
    projected = weekly[0]
    rest, players = {}, {pid: r["player"] for pid, r in last.items()}
    for lines in weekly:
        for pid, r in lines.items():
            rest[pid] = rest.get(pid, 0) + score(r["stats"], scoring)
            players[pid] = r["player"]

    rows = []
    for pid, player in players.items():
        if player.get("position") not in POSITIONS:
            continue
        rows.append({
            "Player Name": f"{player['first_name']} {player['last_name']}",
            "Position": player["position"],
            "Team": normalize_team(player.get("team")),
            "Asset ID": pid,
            "Week": week,
            # A player with no row didn't play (last week) or isn't projected, byes included; blank, not 0
            "Last Week": score(last[pid]["stats"], scoring) if pid in last else "",
            "Projected Week": score(projected[pid]["stats"], scoring) if pid in projected else "",
            "Rest of Season": round(rest[pid], 2) if pid in rest else "",
        })
    rows.sort(key=lambda r: r["Rest of Season"] or 0, reverse=True)
    stamp = date.today().isoformat()
    with open(PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({**r, "Scraped At": stamp} for r in rows)
    print(f"points: {len(rows)} players, week {week} -> {PATH}")


def compare(nflverse, sleeper, sleeper_id=lambda gsis: sleeper_id_from("gsis_id", gsis)):
    mismatches, unmatched = [], []
    for row in nflverse:
        pid = sleeper_id(row["player_id"])
        if pid not in sleeper:
            unmatched.append(row["player_display_name"])
            continue
        stats = sleeper[pid]["stats"]
        for key, column in COMPARED.items():
            theirs, ours = float(row[column] or 0), stats.get(key, 0)
            if abs(ours - theirs) > 1e-6:
                mismatches.append((row["player_display_name"], key, ours, theirs))
    return mismatches, unmatched


def check_failed(mismatches, unmatched, compared):
    # A few disagreeing players are stat corrections settling and only get logged; Sleeper breaking shows up as a
    # large share at once. Players, not stats: one corrected game moves several stats for the same player
    off = len({m[0] for m in mismatches})
    return off > MAX_SHARE * compared or len(unmatched) > MAX_SHARE * compared


def check():
    # The NFL applies stat corrections through Wednesday, so on Tuesday and Wednesday the last finished week isn't
    # final yet and the week before it is checked instead
    state = get("/state/nfl")
    if state["season_type"] != "regular":
        print(f"points check: skipped, Sleeper is in the {state['season_type']} season")
        return
    week = state["week"] - (2 if date.today().weekday() in (1, 2) else 1)
    if week < 1:
        print("points check: no finished week to check yet")
        return
    response = requests.get(NFLVERSE_URL.format(season=state["season"]), headers=HEADERS, timeout=60)
    response.raise_for_status()
    nflverse = [r for r in csv.DictReader(io.StringIO(response.text))
                if r["week"] == str(week) and r["season_type"] == "REG" and r["position"] in POSITIONS]
    if not nflverse:
        raise RuntimeError(f"nflverse has no week {week} stats")
    mismatches, unmatched = compare(nflverse, stat_lines("stats", state["season"], week))
    print(f"points check week {week}: {len(nflverse)} players, {len(mismatches)} stat mismatches, "
          f"{len(unmatched)} missing from Sleeper")
    for m in mismatches[:20]:
        print(f"  {m[0]} {m[1]}: Sleeper {m[2]}, nflverse {m[3]}")
    if unmatched:
        print(f"  missing: {', '.join(unmatched[:20])}")
    if check_failed(mismatches, unmatched, len(nflverse)):
        raise RuntimeError("Sleeper and nflverse disagree on raw stats")


def score_mismatches(matchups, stats, scoring):
    # Sleeper's matchups carry the league's own score for every rostered player, so score() must match them exactly.
    # A player missing from stats didn't play and must have scored 0
    off = []
    for matchup in matchups:
        for pid, points in matchup["players_points"].items():
            ours = score(stats[pid]["stats"], scoring) if pid in stats else 0
            if abs(ours - points) > 0.005:
                off.append((pid, ours, points))
    return off


def check_scoring(league_id):
    state = get("/state/nfl")
    week = state["week"] - 1
    if state["season_type"] != "regular" or week < 1:
        print("scoring check: no finished week to check yet")
        return
    scoring = get(f"/league/{league_id}")["scoring_settings"]
    stats = stat_lines("stats", state["season"], week)
    matchups = get(f"/league/{league_id}/matchups/{week}")
    # Kickers and defenses aren't pulled, so only skill players are checked
    players = sleeper_players()
    for m in matchups:
        m["players_points"] = {pid: p for pid, p in m["players_points"].items()
                               if players.get(pid, {}).get("position") in POSITIONS}
    off = score_mismatches(matchups, stats, scoring)
    checked = sum(len(m["players_points"]) for m in matchups)
    print(f"scoring check week {week}: {checked} rostered players, {len(off)} differ from the league's matchup points")
    for pid, ours, theirs in off[:20]:
        print(f"  {players.get(pid, {}).get('full_name', pid)}: ours {ours}, league {theirs}")
    if off:
        raise RuntimeError("league-scored points differ from Sleeper's matchup points")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from app import LEAGUE_ID
    pull(LEAGUE_ID)
    check()
    check_scoring(LEAGUE_ID)
