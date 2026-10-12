import sys
import time

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
from ids import sleeper_players
from league import league_values

SOURCES = [ktc, fantasycalc, dynastyprocess, rosteraudit, dynasty_daddy, dynastydealer, fantasypros, redraft]


def step(name, fn, failures):
    # A failing source keeps its previous CSV, so one outage shouldn't stop the rest of the daily run
    print(f"\n== {name}")
    start = time.time()
    try:
        fn()
    except Exception as e:
        failures.append(name)
        print(f"FAILED {name}: {e!r}")
    else:
        print(f"ok ({time.time() - start:.1f}s)")


def check_league():
    result = league_values(LEAGUE_ID)
    print(f"{result['league']}: {len(result['teams'])} teams, picks {', '.join(result['pick_seasons'])}")


def refresh():
    failures = []
    # Players first: every scraper matches names and IDs against this file
    step("sleeper players", lambda: sleeper_players(force=True), failures)
    for source in SOURCES:
        step(source.__name__, source.pull, failures)
    step("combine", combine.combine, failures)
    step(f"sleeper league {LEAGUE_ID}", check_league, failures)

    print(f"\nRefresh finished: {len(SOURCES) + 3 - len(failures)} ok, {len(failures)} failed"
          + (f" ({', '.join(failures)})" if failures else ""))
    return failures


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(1 if refresh() else 0)
