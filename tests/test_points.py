# python -m unittest discover tests
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sources"))

import common  # noqa: E402
from points import check_failed, compare, score  # noqa: E402

SCORING = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "rush_yd": 0.1, "rec": 1.0, "fum": 0.0}


class ScoreTest(unittest.TestCase):
    def test_league_scoring_not_sleeper_totals(self):
        # Trevor Lawrence, week 6 2026: Sleeper's pts_ppr is 28.34 because it counts the interception at -1
        stats = {"pass_yd": 306.0, "pass_td": 4.0, "pass_int": 1.0, "rush_yd": 11.0, "pts_ppr": 28.34,
                 "pos_rank_ppr": 3.0, "gp": 1.0}
        self.assertEqual(score(stats, SCORING), 27.34)

    def test_empty_line(self):
        self.assertEqual(score({}, SCORING), 0)


class CompareTest(unittest.TestCase):
    def nflverse(self, gsis, name, **stats):
        row = {c: "0" for c in ("passing_yards", "passing_tds", "passing_interceptions", "rushing_yards",
                                "rushing_tds", "receptions", "receiving_yards", "receiving_tds", "fumbles_lost_total")}
        return {**row, "player_id": gsis, "player_display_name": name, **stats}

    def test_mismatch_and_unmatched(self):
        nflverse = [self.nflverse("G1", "Same", receptions="5", receiving_yards="62"),
                    self.nflverse("G2", "Off", receptions="5"),
                    self.nflverse("G3", "Missing")]
        sleeper = {"S1": {"stats": {"rec": 5.0, "rec_yd": 62.0, "pts_ppr": 11.2}},
                   "S2": {"stats": {"rec": 4.0}}}
        mismatches, unmatched = compare(nflverse, sleeper, sleeper_id={"G1": "S1", "G2": "S2"}.get)
        self.assertEqual(mismatches, [("Off", "rec", 4.0, 5.0)])
        self.assertEqual(unmatched, ["Missing"])

    def test_only_a_large_share_fails(self):
        # One corrected game: three stats, one player, out of 100. Logged, not failed
        corrected = [("A", "rec", 4.0, 5.0), ("A", "rec_yd", 40.0, 52.0), ("A", "rec_td", 0.0, 1.0)]
        self.assertFalse(check_failed(corrected, [], 100))
        broken = [(f"P{i}", "rec", 0.0, 3.0) for i in range(11)]
        self.assertTrue(check_failed(broken, [], 100))
        self.assertTrue(check_failed([], [f"P{i}" for i in range(11)], 100))


class SleeperGetTest(unittest.TestCase):
    def response(self, status, headers=None):
        return mock.Mock(status_code=status, headers=headers or {}, raise_for_status=mock.Mock())

    def test_backs_off_on_429(self):
        replies = [self.response(429, {"Retry-After": "7"}), self.response(429), self.response(200)]
        with mock.patch.object(common.requests, "get", side_effect=replies) as get, \
                mock.patch.object(common.time, "sleep") as sleep:
            self.assertIs(common.sleeper_get("https://x"), replies[2])
        self.assertEqual(get.call_count, 3)
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertIn(7.0, waits)  # honours Retry-After
        self.assertIn(4, waits)  # then exponential backoff

    def test_spaces_calls(self):
        with mock.patch.object(common.requests, "get", return_value=self.response(200)), \
                mock.patch.object(common.time, "sleep") as sleep:
            common.sleeper_get("https://x")
            common.sleeper_get("https://x")
        self.assertTrue(any(0 < c.args[0] <= common.SLEEPER_INTERVAL for c in sleep.call_args_list))


if __name__ == "__main__":
    unittest.main()
