import csv
import io
import json
import re
import time
from functools import cache

import requests

from common import DATA_DIR, HEADERS

CROSSWALK_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
# Sleeper asks that the full player dump be fetched at most once per day
SLEEPER_CACHE = DATA_DIR / "sleeper_players.json"
SLEEPER_MAX_AGE = 24 * 60 * 60
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}
# Source name -> Sleeper ID, for players neither the crosswalk nor the name fallback can match
ALIASES = {
    "Matthew Hibner": "13324",
    # listed as DB in Sleeper, WR in every value source
    "Travis Hunter": "12530",
}

PICK_PATTERNS = [
    (re.compile(r"(\d{4}) (Early|Mid|Late) (\d)(?:st|nd|rd|th)$"), lambda m: (m[1], m[3], m[2].lower())),
    (re.compile(r"(\d{4}) (\d)(?:st|nd|rd|th) \((Early|Mid|Late)\)$"), lambda m: (m[1], m[2], m[3].lower())),
    (re.compile(r"(\d{4}) Round (\d) (Early|Mid|Late)$"), lambda m: (m[1], m[2], m[3].lower())),
    (re.compile(r"(\d{4}) (\d)(?:st|nd|rd|th)$"), lambda m: (m[1], m[2], "any")),
    (re.compile(r"(\d{4}) Pick (\d)\.(\d{2})$"), lambda m: (m[1], m[2], m[3])),
]


def pick_id(name):
    for pattern, parts in PICK_PATTERNS:
        m = pattern.match(name)
        if m:
            return "-".join(parts(m))
    raise ValueError(f"Unknown pick format {name!r}; add a pattern to PICK_PATTERNS")


@cache
def _crosswalk():
    text = requests.get(CROSSWALK_URL, headers=HEADERS, timeout=60).text
    return list(csv.DictReader(io.StringIO(text)))


@cache
def _crosswalk_index(field):
    return {r[field]: r["sleeper_id"] for r in _crosswalk() if r[field] != "NA" and r["sleeper_id"] != "NA"}


def sleeper_id_from(field, value):
    return _crosswalk_index(field).get(str(value)) if value else None


@cache
def sleeper_players():
    DATA_DIR.mkdir(exist_ok=True)
    if not SLEEPER_CACHE.exists() or time.time() - SLEEPER_CACHE.stat().st_mtime > SLEEPER_MAX_AGE:
        response = requests.get(SLEEPER_URL, headers=HEADERS, timeout=120)
        response.raise_for_status()
        # parse before caching so an error page never becomes the cache for a day
        json.loads(response.text)
        SLEEPER_CACHE.write_text(response.text, encoding="utf-8")
    return json.loads(SLEEPER_CACHE.read_text(encoding="utf-8"))


def _norm(name):
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", name.lower())
    return re.sub(r"[^a-z]", "", name)


@cache
def _name_index():
    index = {}
    for sid, p in sleeper_players().items():
        if p.get("position") in FANTASY_POSITIONS and p.get("full_name"):
            index.setdefault((_norm(p["full_name"]), p["position"]), []).append((sid, p))
    return index


def sleeper_id_by_name(name, position):
    if name in ALIASES:
        return ALIASES[name]
    candidates = _name_index().get((_norm(name), position), [])
    # same-name players (e.g. two Mike Williams): only accept a single active match, never guess
    if len(candidates) > 1:
        candidates = [c for c in candidates if c[1].get("active")]
    return candidates[0][0] if len(candidates) == 1 else None


def assign_ids(source, rows):
    players = sleeper_players()
    for r in rows:
        if r["Type"] == "Pick":
            r["Asset ID"] = pick_id(r["Player Name"])
            continue
        if not r["Asset ID"]:
            r["Asset ID"] = sleeper_id_by_name(r["Player Name"], r["Position"])
        if r["Asset ID"] in players:
            r["Player Name"] = players[r["Asset ID"]]["full_name"]
        else:
            print(f"  {source}: no Sleeper match for {r['Player Name']} ({r['Position']}, value {r['Value']}, id {r['Asset ID']})")
    return rows
