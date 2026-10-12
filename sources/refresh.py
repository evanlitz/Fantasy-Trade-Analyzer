import shutil
import sys
import time
from datetime import date

import combine
import dynasty_daddy
import dynastydealer
import dynastyprocess
import fantasycalc
import fantasypros
import ktc
import redraft
import rosteraudit
from app import LEAGUE_ID
from common import DATA_DIR
from ids import sleeper_players
from league import league_values

SOURCES = [ktc, fantasycalc, dynastyprocess, rosteraudit, dynasty_daddy, dynastydealer, fantasypros, redraft]


def step(name, fn, failures, ran):
    # A failing source keeps its previous CSV, so one outage shouldn't stop the rest of the daily run
    ran.append(name)
    print(f"\n== {name}")
    start = time.time()
    try:
        fn()
    except Exception as e:
        failures.append(name)
        print(f"FAILED {name}: {e!r}")
    else:
        print(f"ok ({time.time() - start:.1f}s)")


def snapshot():
    # consensus.csv is overwritten daily; dated copies are the only record of how values move.
    # A second run on the same day replaces that day's copy.
    history = DATA_DIR / "history"
    history.mkdir(exist_ok=True)
    path = history / f"{date.today().isoformat()}.csv"
    shutil.copyfile(DATA_DIR / "consensus.csv", path)
    print(f"snapshot -> {path}")


def check_league():
    result = league_values(LEAGUE_ID)
    print(f"{result['league']}: {len(result['teams'])} teams, picks {', '.join(result['pick_seasons'])}")


def refresh():
    failures, ran = [], []
    # Players first: every scraper matches names and IDs against this file
    step("sleeper players", lambda: sleeper_players(force=True), failures, ran)
    for source in SOURCES:
        step(source.__name__, source.pull, failures, ran)
    step("combine", combine.combine, failures, ran)
    # Skipped when combine failed, so yesterday's consensus is never saved under today's date
    if "combine" not in failures:
        step("snapshot", snapshot, failures, ran)
    step(f"sleeper league {LEAGUE_ID}", check_league, failures, ran)

    print(f"\nRefresh finished: {len(ran) - len(failures)} ok, {len(failures)} failed"
          + (f" ({', '.join(failures)})" if failures else ""))
    return failures


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(1 if refresh() else 0)
