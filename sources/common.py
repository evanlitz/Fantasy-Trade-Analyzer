import csv
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# RosterAudit blocks default python/curl user agents
HEADERS = {"User-Agent": "DynastyTradeAnal/0.1"}
# Sleeper IP-blocks above 1000 calls a minute (docs.sleeper.com). Spacing calls 0.5s apart caps one process at 120 a
# minute, so the app server and a refresh running at the same time still stay under a quarter of the limit
SLEEPER_INTERVAL = 0.5
SLEEPER_RETRIES = 3
_sleeper_lock = threading.Lock()
_sleeper_last = [0.0]
COLUMNS = ["Player Name", "Type", "Position", "Team", "Age", "Value", "Asset ID", "Scraped At"]

TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "FA",
}
TEAM_ALIASES = {
    "GBP": "GB", "KCC": "KC", "LVR": "LV", "NEP": "NE", "NOS": "NO", "SFO": "SF", "TBB": "TB",
    "JAC": "JAX", "LA": "LAR", "": "FA", None: "FA",
}


def sleeper_get(url, params=None, timeout=30):
    # Every Sleeper call goes through here. The lock is held while waiting, so the app server's threads queue up
    # instead of firing together. A 429 means we're already close to a block: back off and retry, never hammer
    for attempt in range(SLEEPER_RETRIES + 1):
        with _sleeper_lock:
            wait = _sleeper_last[0] + SLEEPER_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            _sleeper_last[0] = time.monotonic()
        if response.status_code != 429 or attempt == SLEEPER_RETRIES:
            break
        time.sleep(float(response.headers.get("Retry-After") or 2 ** (attempt + 1)))
    response.raise_for_status()
    return response


def normalize_team(code):
    team = TEAM_ALIASES.get(code, code)
    if team not in TEAMS:
        raise ValueError(f"Unknown team code {code!r}; add it to TEAM_ALIASES")
    return team


def write_csv(source, rows):
    DATA_DIR.mkdir(exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        r["Scraped At"] = scraped_at
        if r["Type"] == "Player":
            r["Team"] = normalize_team(r["Team"])
    rows = sorted(rows, key=lambda r: r["Value"], reverse=True)
    path = DATA_DIR / f"{source}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{source}: {len(rows)} rows ({sum(r['Type'] == 'Pick' for r in rows)} picks) -> {path}")
