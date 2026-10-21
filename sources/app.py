import json
import time
from collections import Counter
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from common import DATA_DIR
from league import League
from trade import evaluate, load_assets

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PORT = 8000
LEAGUE_ID = "1395495049021652992"
LEAGUE_CACHE_SECONDS = 600
league_cache = {"at": 0, "data": None}


def cached_league():
    # Rosters move slowly; this keeps page reloads from re-hitting Sleeper five times each,
    # and lets trades reuse the built rosters and simulated lineups
    if time.time() - league_cache["at"] > LEAGUE_CACHE_SECONDS:
        league_cache["data"] = League.load(LEAGUE_ID)
        league_cache["at"] = time.time()
    return league_cache["data"]


def asset_list():
    seen = Counter()
    out = []
    for a in load_assets():
        if a["Type"] == "Player":
            seen[a["Position"]] += 1
        out.append({
            "id": a["Asset ID"], "name": a["Player Name"], "type": a["Type"], "position": a["Position"],
            "team": a["Team"], "age": float(a["Age"]) if a["Age"] else None, "value": a["Value"],
            "posRank": seen[a["Position"]] if a["Type"] == "Player" else None,
        })
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/assets":
            built = datetime.fromtimestamp((DATA_DIR / "consensus.csv").stat().st_mtime)
            return self.send_json({"assets": asset_list(), "built": built.strftime("%b %d, %H:%M")})
        if self.path == "/api/league":
            return self.send_json(cached_league().base)
        url = urlparse(self.path)
        if url.path == "/api/league/free-agents":
            # ?team=<roster id>: free agents re-scored onto that team
            lg = cached_league()
            team = parse_qs(url.query).get("team", [""])[0]
            if not team.isdigit() or int(team) not in lg.rosters:
                return self.send_json({"error": "team must be a roster id in this league"}, 400)
            return self.send_json(lg.free_agents(int(team)))
        return super().do_GET()

    def do_POST(self):
        if self.path not in ("/api/evaluate", "/api/league/evaluate"):
            return self.send_json({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/league/evaluate":
            return self.league_evaluate(body)
        try:
            r = evaluate(body["a"], body["b"])
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({
            "totalA": r["total_a"], "totalB": r["total_b"], "adjA": r["adj_a"], "adjB": r["adj_b"],
            "finalA": r["final_a"], "finalB": r["final_b"], "winner": r["winner"], "fair": r["fair"],
            "margin": r["margin"], "suggestions": [s["Asset ID"] for s in r["suggestions"]],
        })

    def league_evaluate(self, body):
        # Both sides are league asset IDs (Sleeper player IDs, picks as season-round-r<original roster>), one team each
        try:
            r = cached_league().trade(body["a"], body["b"])
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({
            "totalA": r["total_a"], "totalB": r["total_b"], "adjA": r["adj_a"], "adjB": r["adj_b"],
            "finalA": r["final_a"], "finalB": r["final_b"], "winner": r["winner"], "fair": r["fair"],
            "margin": r["margin"], "suggestions": [s["Asset ID"] for s in r["suggestions"]],
            "teams": r["teams"],
        })


if __name__ == "__main__":
    print(f"Ledger on http://localhost:{PORT}")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
