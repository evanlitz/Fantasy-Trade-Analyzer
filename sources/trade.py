import csv
import sys
from difflib import get_close_matches

from common import DATA_DIR
from ids import _norm

# Ported from KTC's trade calculator (ALGOTOUSE=2: adjustPackageNew/processVNew/solveForX/evaluateTrade
# in keeptradecut.com/js/site.min.js, read 2026-10-10)
FAIR_PERCENT = 5  # KTC's default variance slider
MAX_ADJUSTMENT = 10000  # KTC's MAXPLAYERVAL


def load_assets():
    with open(DATA_DIR / "consensus.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["Value"] = int(r["Value"])
    return rows


def find(query, assets):
    q = query.strip().lower()
    matches = [a for a in assets if q in (a["Asset ID"].lower(), a["Player Name"].lower())]
    if not matches:
        matches = [a for a in assets if a["Type"] == "Player" and _norm(a["Player Name"]) == _norm(query)]
    if not matches:
        matches = [a for a in assets if a["Type"] == "Player" and _norm(query) in _norm(a["Player Name"])]
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = ", ".join(f"{a['Player Name']} ({a['Position']} {a['Team']}, id {a['Asset ID']})" for a in matches)
        raise ValueError(f"{query!r} is ambiguous: {options}")
    close = get_close_matches(query, [a["Player Name"] for a in assets], n=3)
    raise ValueError(f"{query!r} not found" + (f"; did you mean {', '.join(close)}?" if close else ""))


def raw(value, best, top):
    # Studs keep more of their value than depth pieces; best is the top asset in the trade
    return value * (0.2 + 0.7 * (value / (1.05 * best)) ** 1.25 + 0.1 * (value / (top + 100)) ** 1.4)


def value_for_raw(target, best, top):
    # Inverse of raw() by Newton's method; raw() is increasing and convex, so starting high converges
    x = 5 * target
    for _ in range(50):
        step = (raw(x, best, top) - target) / (0.2 + 1.575 * (x / (1.05 * best)) ** 1.25 + 0.24 * (x / (top + 100)) ** 1.4)
        x -= step
        if abs(step) < 1e-6:
            break
    return x


def equal_within(x, y):
    x, y = max(0, x), max(0, y)
    return round(min(100, abs(x - y) / (x + y) * 100), 1) <= FAIR_PERCENT


def adjustments(total_a, total_b, raw_a, raw_b, best, top):
    # Mirrors adjustPackageNew branch for branch, including its asymmetries
    gap = lambda diff: value_for_raw(diff, best, top)
    c = abs(raw_a - raw_b) // 1
    adj_a = adj_b = 0
    if equal_within(total_a, total_b) and equal_within(raw_a, raw_b):
        if raw_a > raw_b:
            b = total_b + gap(c) - total_a
            adj_a, adj_b = (b, 0) if b > 0 else (0, -b)
        elif raw_b > raw_a:
            b = total_a + gap(c) - total_b
            adj_a, adj_b = (0, b) if b > 0 else (-b, 0)
    elif raw_a / total_a > raw_b / total_b:
        if raw_a > raw_b:
            b = total_b + gap(c) - total_a
            adj_a, adj_b = (b, 0) if b > 0 else (0, abs(b))
        elif total_a != total_b:
            w = gap(abs(raw_a - raw_b))
            if w > 0:
                if total_a > total_b:
                    adj_b = w - (total_a - total_b)
                else:
                    t = w - (total_b - total_a)
                    if t <= 0:
                        adj_a = -t
                    elif t <= MAX_ADJUSTMENT:
                        adj_b = t
    else:
        if raw_b > raw_a:
            b = total_a + gap(c) - total_b
            adj_a, adj_b = (0, b) if b > 0 else (abs(b), 0)
        elif total_a != total_b:
            w = gap(abs(raw_a - raw_b))
            if w > 0:
                if total_a < total_b:
                    adj_a = w - (total_b - total_a)
                else:
                    t = w - (total_a - total_b)
                    if t <= 0:
                        adj_b = -t
                    elif t <= MAX_ADJUSTMENT:
                        adj_a = t
    return adj_a, adj_b


def score(a, b, top):
    best = max(r["Value"] for r in a + b)
    total_a, total_b = sum(r["Value"] for r in a), sum(r["Value"] for r in b)
    raw_a, raw_b = sum(raw(r["Value"], best, top) for r in a), sum(raw(r["Value"], best, top) for r in b)
    adj_a, adj_b = adjustments(total_a, total_b, raw_a, raw_b, best, top)
    return {
        "total_a": total_a, "total_b": total_b,
        "adj_a": adj_a, "adj_b": adj_b,
        "final_a": max(0, total_a + adj_a), "final_b": max(0, total_b + adj_b),
    }


def verdict(a, b, top, pool_a, pool_b):
    # pool_a/pool_b: assets that could be added to that side to even it (a team's own roster in league trades)
    s = score(a, b, top)
    winner = "A" if s["final_a"] >= s["final_b"] else "B"
    fair = equal_within(s["final_a"], s["final_b"])

    # Real assets that come closest to evening the trade when added to the losing side
    suggestions = []
    if not fair:
        in_trade = {r["Asset ID"] for r in a + b}

        def gap_after(extra):
            t = score(a, b + [extra], top) if winner == "A" else score(a + [extra], b, top)
            return abs(t["final_a"] - t["final_b"])

        pool = pool_b if winner == "A" else pool_a
        suggestions = sorted((r for r in pool if r["Asset ID"] not in in_trade), key=gap_after)[:3]

    return {**s, "side_a": a, "side_b": b, "winner": winner, "fair": fair,
            "margin": abs(s["final_a"] - s["final_b"]), "suggestions": suggestions}


def evaluate(side_a, side_b, assets=None):
    if not side_a or not side_b:
        raise ValueError('Both sides need at least one asset, e.g. "Jahmyr Gibbs" vs "Kenneth Walker, Garrett Wilson"')
    assets = assets or load_assets()
    a = [find(q, assets) for q in side_a]
    b = [find(q, assets) for q in side_b]
    return verdict(a, b, max(r["Value"] for r in assets), assets, assets)


def report(result):
    for label in ("a", "b"):
        adj = result["adj_" + label]
        print(f"Side {label.upper()}  total {result['total_' + label]}" + (f"  + adjustment {adj:.0f} = {result['final_' + label]:.0f}" if adj else ""))
        for r in result["side_" + label]:
            print(f"  {r['Player Name']:<26} {r['Position']:<4} {r['Value']:>5}")
    loser = "B" if result["winner"] == "A" else "A"
    if result["fair"]:
        print(f"Fair trade (within {FAIR_PERCENT}%)")
    else:
        print(f"Favors side {result['winner']}. Add an asset worth ~{result['margin']:.0f} to side {loser} to even it, e.g.:")
        for r in result["suggestions"]:
            print(f"  {r['Player Name']:<26} {r['Position']:<4} {r['Value']:>5}")


if __name__ == "__main__":
    # python trade.py "Jahmyr Gibbs" vs "Kenneth Walker, Garrett Wilson"
    a, _, b = " ".join(sys.argv[1:]).partition(" vs ")
    try:
        report(evaluate([s for s in a.split(",") if s.strip()], [s for s in b.split(",") if s.strip()]))
    except ValueError as e:
        sys.exit(str(e))
