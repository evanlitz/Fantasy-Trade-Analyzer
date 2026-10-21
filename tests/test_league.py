# python -m unittest discover tests
# A made-up 4-team league built from data/consensus.csv, so nothing here touches the network
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sources"))

from league import START_CHANGE, League, start_shares  # noqa: E402
from trade import evaluate, load_assets  # noqa: E402

POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN", "BN", "BN"]
TEAMS = 4
PER_TEAM = 11  # one open roster spot each


def make_league(full=False):
    assets = load_assets()
    players = [a for a in assets if a["Type"] == "Player"]
    by_pos = {pos: [a for a in players if a["Position"] == pos] for pos in ("QB", "RB", "WR", "TE")}
    # Every team gets a startable lineup: 2 QB, 4 RB, 4 WR, 1 TE (+1 WR when full), dealt round robin
    need = {"QB": 2, "RB": 4, "WR": 5 if full else 4, "TE": 1}
    rosters = [{"roster_id": i + 1, "owner_id": f"u{i + 1}", "players": [], "taxi": [], "reserve": [],
                "settings": {"wins": 3 - i, "losses": i, "fpts": 100 - i}} for i in range(TEAMS)]
    for pos, n in need.items():
        for k in range(n * TEAMS):
            rosters[k % TEAMS]["players"].append(by_pos[pos][k]["Asset ID"])
    rosters[3]["taxi"] = [rosters[3]["players"][-1]]
    raw = {
        "league": {"name": "Test", "season": "2026", "roster_positions": POSITIONS, "settings": {"draft_rounds": 2}},
        "users": [{"user_id": f"u{i + 1}", "display_name": f"Team {i + 1}"} for i in range(TEAMS)],
        "rosters": rosters,
        "traded": [{"season": "2027", "round": 1, "roster_id": 4, "owner_id": 1}],
        "drafts": [{"season": "2026", "status": "complete"}],
    }
    # Redraft values stand in as dynasty values scaled down; only their order matters here
    now = {a["Asset ID"]: a["Value"] / 10 for a in players}
    sleeper = {a["Asset ID"]: {"position": a["Position"], "full_name": a["Player Name"]} for a in players}
    return League(raw, assets, now, sleeper)


def roster_ids(lg, rid):
    return [p["id"] for p in lg.rosters[rid]["players"]]


def best(lg, rid):
    return max(lg.rosters[rid]["players"], key=lambda p: p["raw"])["id"]


class LeagueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = make_league()

    def test_assets_have_one_owner(self):
        self.assertEqual(self.lg.owner["2027-1-r4"], 1)
        self.assertEqual(sum(len(t["players"]) + len(t["picks"]) for t in self.lg.rosters.values()), len(self.lg.owner))

    def test_start_shares_ignore_roster_order(self):
        # The point of per-player seeding: same players, any order, identical shares
        active = [p for p in self.lg.rosters[1]["players"]]
        shuffled = active[:]
        random.Random(1).shuffle(shuffled)
        self.assertEqual(start_shares(active, self.lg.slots, self.lg.absent | self._absent(active)),
                         start_shares(shuffled, self.lg.slots, self.lg.absent | self._absent(active)))

    def _absent(self, players):
        from league import absences
        return {p["id"]: absences(p["id"], p["position"]) for p in players}

    def test_rescoring_is_deterministic(self):
        again = self.lg.score(self.lg.rosters)
        for t in self.lg.base["teams"]:
            u = self.lg.team(again, t["roster_id"])
            self.assertEqual((t["win_now"], t["dynasty"], t["tier"]), (u["win_now"], u["dynasty"], u["tier"]))

    def test_trade_moves_assets(self):
        a, b = roster_ids(self.lg, 1)[0], roster_ids(self.lg, 2)[0]
        rosters = self.lg.after_trade(1, {a}, 2, {b})
        self.assertIn(b, [p["id"] for p in rosters[1]["players"]])
        self.assertNotIn(a, [p["id"] for p in rosters[1]["players"]])
        self.assertIn(a, [p["id"] for p in rosters[2]["players"]])
        self.assertIs(rosters[3], self.lg.rosters[3])

    def test_unaffected_teams_keep_win_now(self):
        a, b = roster_ids(self.lg, 1)[0], roster_ids(self.lg, 2)[0]
        after = self.lg.score(self.lg.after_trade(1, {a}, 2, {b}))
        for rid in (3, 4):
            self.assertEqual(self.lg.team(after, rid)["win_now"], self.lg.team(self.lg.base, rid)["win_now"])

    def test_bench_swap_barely_moves_win_now(self):
        # Each team's least-started players: swapping them should move win-now by noise at most
        least = lambda rid: min((p for p in self.lg.team(self.lg.base, rid)["players"] if not p["taxi"]),
                                key=lambda p: p["start"])
        a, b = least(1), least(2)
        r = self.lg.trade([a["id"]], [b["id"]])
        for side in ("a", "b"):
            t = r["teams"][side]
            change = abs(t["after"]["win_now"] - t["before"]["win_now"]) / t["before"]["win_now"]
            self.assertLess(change, 0.02)

    def test_star_for_bench_shows_in_starts(self):
        star = best(self.lg, 1)
        bench = min(self.lg.team(self.lg.base, 2)["players"], key=lambda p: p["start"])["id"]
        r = self.lg.trade([star], [bench])
        self.assertLess(r["teams"]["a"]["after"]["win_now"], r["teams"]["a"]["before"]["win_now"])
        self.assertGreater(r["teams"]["b"]["after"]["win_now"], r["teams"]["b"]["before"]["win_now"])
        # Arrivals are always listed (first); players already there only when their share moved enough
        b = r["teams"]["b"]["starts"]
        self.assertEqual([s["id"] for s in b if s["arrived"]], [star])
        self.assertTrue(b[0]["arrived"])
        self.assertTrue(all(abs(s["after"] - s["before"]) >= START_CHANGE for s in b if not s["arrived"]))
        # Someone on team 2 loses starts to the star
        self.assertTrue(any(s["after"] < s["before"] for s in b if not s["arrived"]))

    def test_validation(self):
        p1, p1b, p2 = roster_ids(self.lg, 1)[0], roster_ids(self.lg, 1)[1], roster_ids(self.lg, 2)[0]
        cases = [([p1], [p1b], "same team"), ([p1, p2], [roster_ids(self.lg, 3)[0]], "2 teams"),
                 ([p1], [p1], "both sides"), (["nope"], [p2], "not on any roster"), ([], [p2], "empty")]
        for a, b, msg in cases:
            with self.assertRaisesRegex(ValueError, msg):
                self.lg.trade(a, b)

    def test_picks_trade_and_price_at_market(self):
        pick = next(p for p in self.lg.rosters[2]["picks"] if p["season"] == "2027" and p["round"] == 1)
        r = self.lg.trade([roster_ids(self.lg, 1)[5]], [pick["id"]])
        self.assertEqual(r["side_b"][0]["Value"],
                         next(p["value"] for p in self.lg.team(self.lg.base, 2)["picks"] if p["id"] == pick["id"]))

    def test_suggestions_come_from_losing_team(self):
        star = best(self.lg, 1)
        bench = min(self.lg.rosters[2]["players"], key=lambda p: p["raw"])["id"]
        r = self.lg.trade([star], [bench])
        self.assertFalse(r["fair"])
        loser = 2 if r["winner"] == "A" else 1
        self.assertTrue(r["suggestions"])
        self.assertTrue(all(self.lg.owner[s["Asset ID"]] == loser for s in r["suggestions"]))

    def test_next_draft_tiers_follow_win_now(self):
        # Team 1 has the best record and lineup, so its 2027 1st projects late. Gutting its starters drops its
        # win-now rank; the record half stays, so the pick moves earlier but not necessarily to early.
        order = ["early", "mid", "late"]
        before = next(p["tier"] for p in self.lg.team(self.lg.base, 1)["picks"] if p["id"] == "2027-1-r1")
        self.assertEqual(before, "late")
        starters = sorted(self.lg.team(self.lg.base, 1)["players"], key=lambda p: -p["start"])[:4]
        bench = sorted((p for p in self.lg.team(self.lg.base, 4)["players"] if not p["taxi"]), key=lambda p: p["start"])[:4]
        r = self.lg.trade([p["id"] for p in starters], [p["id"] for p in bench])
        moved = {p["id"]: p for t in r["teams"].values() for p in t["pick_tiers"]}
        self.assertIn("2027-1-r1", moved)
        self.assertLess(order.index(moved["2027-1-r1"]["after"]), order.index(before))
        # Later drafts are never projected
        self.assertFalse(any(p["season"] != "2027" for p in moved.values()))

    def test_lineup_matches_slots_and_simulation(self):
        from league import best_lineup
        for t in self.lg.base["teams"]:
            self.assertEqual([s["slot"] for s in t["lineup"]], self.lg.slots)
            active = [p for p in t["players"] if not p["taxi"]]
            self.assertEqual(sorted(s["id"] for s in t["lineup"] if s["id"]),
                             sorted(p["id"] for p in best_lineup(active, self.lg.slots)))

    def test_free_agents_skip_rostered_and_fill_open_spot(self):
        r = self.lg.free_agents(1)
        self.assertFalse(r["full"])
        self.assertTrue(r["free_agents"])
        self.assertFalse({f["id"] for f in r["free_agents"]} & self.lg.taken)
        self.assertIsNone(r["drop"])
        # With a spot open, adding a valued player can't lower the dynasty score
        self.assertTrue(all(f["dynasty_change"] >= 0 for f in r["free_agents"]))

    def test_generic_calculator_unchanged(self):
        r = evaluate(["Jahmyr Gibbs"], ["Bijan Robinson"])
        self.assertIn(r["winner"], ("A", "B"))


class RosterLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = make_league(full=True)

    def test_two_for_one_cuts_cheapest(self):
        # Team 2 is at the 12-spot limit; taking two players for one forces one cut
        a = roster_ids(self.lg, 1)[:2]
        b = [roster_ids(self.lg, 2)[0]]
        rosters = self.lg.after_trade(1, set(a), 2, set(b))
        self.assertEqual(rosters[2]["cuts"], 1)
        self.assertEqual(rosters[2]["spots"], self.lg.roster_limit)
        kept = {p["id"] for p in rosters[2]["players"]}
        cheapest = min((p for p in self.lg.rosters[2]["players"] if p["id"] not in b), key=lambda p: p["raw"])
        self.assertNotIn(cheapest["id"], kept)
        self.assertTrue(set(a) <= kept)
        self.assertEqual(rosters[1]["cuts"], 0)

    def test_full_roster_free_agent_needs_a_drop(self):
        r = self.lg.free_agents(2)
        self.assertTrue(r["full"])
        mine = {p["id"] for p in self.lg.rosters[2]["players"] if not p["taxi"] and not p["reserve"]}
        self.assertIn(r["drop"]["id"], mine)
        self.assertNotIn(r["drop"]["id"], {f["id"] for f in r["free_agents"]})
        # Re-scoring for free agents leaves the league's base scores alone
        self.assertEqual(self.lg.score(self.lg.rosters)["teams"], self.lg.base["teams"])

    def test_even_trade_cuts_nothing(self):
        rosters = self.lg.after_trade(1, {roster_ids(self.lg, 1)[0]}, 2, {roster_ids(self.lg, 2)[0]})
        self.assertEqual((rosters[1]["cuts"], rosters[2]["cuts"]), (0, 0))

    def test_taxi_player_does_not_free_a_spot(self):
        # Team 4 holds 11 active + 1 taxi. Its taxi player for two actives makes 13 active: one cut,
        # where counting the taxi player as a freed spot would have made it 12 and none
        taxi = self.lg.rosters[4]["players"][-1]
        self.assertTrue(taxi["taxi"])
        rosters = self.lg.after_trade(4, {taxi["id"]}, 1, set(roster_ids(self.lg, 1)[:2]))
        self.assertEqual(rosters[4]["cuts"], 1)
        self.assertEqual(rosters[1]["cuts"], 0)
        arrived = next(p for p in rosters[1]["players"] if p["id"] == taxi["id"])
        self.assertFalse(arrived["taxi"])


if __name__ == "__main__":
    unittest.main()
