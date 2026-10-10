import csv
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# RosterAudit blocks default python/curl user agents
HEADERS = {"User-Agent": "DynastyTradeAnal/0.1"}
COLUMNS = ["Player Name", "Type", "Position", "Team", "Age", "Value", "Asset ID", "Scraped At"]

TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "FA",
}
TEAM_ALIASES = {
    "GBP": "GB", "KCC": "KC", "LVR": "LV", "NEP": "NE", "NOS": "NO", "SFO": "SF", "TBB": "TB",
    "JAC": "JAX", "LA": "LAR", "": "FA", None: "FA",
}


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
