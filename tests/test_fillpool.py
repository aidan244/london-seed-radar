"""The fill-pool loop: it stops at the target, stops on convergence (a
round that adds nothing), honours the max-rounds cap, and never relaxes
the gates (it only orchestrates the real stages, so the gate logic is
unchanged). The stage runs and the count are injected so these tests need
no database and no network."""

import unittest

from radar import dashboard, fillpool


class TestFillPool(unittest.TestCase):
    def _counter(self, values):
        seq = iter(values)
        return lambda: next(seq)

    def test_stops_at_target(self):
        res = fillpool.fill_pool(
            target=10, max_rounds=8,
            _round=lambda: (True, ""),
            _count=self._counter([3, 7, 10]))   # start 3, then 7, then 10
        self.assertTrue(res["reached"])
        self.assertEqual(res["end"], 10)
        self.assertEqual(res["reason"], "target reached")
        self.assertEqual(len(res["rounds"]), 2)

    def test_stops_on_convergence(self):
        res = fillpool.fill_pool(
            target=10, max_rounds=8,
            _round=lambda: (True, ""),
            _count=self._counter([1, 2, 2]))    # plateaus at 2
        self.assertFalse(res["reached"])
        self.assertEqual(res["end"], 2)
        self.assertIn("exhausted", res["reason"])

    def test_already_at_target_runs_no_rounds(self):
        res = fillpool.fill_pool(
            target=5, max_rounds=8,
            _round=lambda: (True, ""),
            _count=self._counter([5]))
        self.assertTrue(res["reached"])
        self.assertEqual(res["rounds"], [])

    def test_max_rounds_cap(self):
        # always adds one, never reaches the target within the cap
        box = {"n": 0}
        def grow():
            box["n"] += 1
            return box["n"]
        res = fillpool.fill_pool(
            target=100, max_rounds=3, _round=lambda: (True, ""), _count=grow)
        self.assertFalse(res["reached"])
        self.assertEqual(len(res["rounds"]), 3)
        self.assertIn("max-rounds", res["reason"])

    def test_stage_failure_stops_and_reports(self):
        res = fillpool.fill_pool(
            target=10, max_rounds=8,
            _round=lambda: (False, "ingest failed (rc=2)"),
            _count=self._counter([0]))
        self.assertFalse(res["reached"])
        self.assertEqual(res["reason"], "ingest failed (rc=2)")

    def test_round_runs_domains_between_ingest_and_sieve(self):
        """domains must run after ingest and before sieve, so a discovered
        company gets a verified website before the reality gate."""
        calls = []
        orig = {}
        for name in ("ingest", "domains", "sieve", "enrich"):
            mod = getattr(fillpool, name)
            orig[name] = mod.main
            mod.main = (lambda n: (lambda argv=None: calls.append(n) or 0))(name)
        self.addCleanup(lambda: [setattr(getattr(fillpool, n), "main", m)
                                 for n, m in orig.items()])
        ok, _ = fillpool._run_pipeline_round(None, False)
        self.assertTrue(ok)
        self.assertEqual(calls, ["ingest", "domains", "sieve", "enrich"])

    def test_is_a_serve_action(self):
        self.assertIn("fill_pool", dashboard.SERVE_ACTIONS)


if __name__ == "__main__":
    unittest.main()
