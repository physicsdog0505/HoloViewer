import unittest
from ptt_offline.activate_production_publisher import BINDINGS, PRODUCTION_PROFILE


class ProductionPublisherBudgetTests(unittest.TestCase):
    def test_free_tier_safe_snapshot_profile_is_locked(self):
        p=PRODUCTION_PROFILE
        self.assertEqual(p["rows"],10)
        self.assertEqual(p["max_batches"],1)
        self.assertEqual(p["burst_max_batches"],3)
        self.assertEqual(p["max_articles"],4)
        self.assertEqual(p["queries"],60)
        self.assertEqual(p["writes"],24)
        # d1_owner_writer conservative one-AID formulas:
        # statements = thread + 2/row + state; read budget = 3/row.
        worst_writes=2+2*p["rows"]
        worst_queries=(2+2*p["rows"])+3*p["rows"]
        self.assertLessEqual(worst_writes,p["writes"])
        self.assertLessEqual(worst_queries,p["queries"])
        self.assertLessEqual(p["rows"]*p["max_batches"],10)
        self.assertLessEqual(p["rows"]*p["burst_max_batches"],30)

    def test_worker_caps_are_derived_from_same_profile(self):
        self.assertEqual(BINDINGS["PTT_PUBLISH_MAX_ROWS"],str(PRODUCTION_PROFILE["rows"]))
        self.assertEqual(BINDINGS["PTT_PUBLISH_MAX_QUERIES"],str(PRODUCTION_PROFILE["queries"]))
        self.assertEqual(BINDINGS["PTT_PUBLISH_MAX_WRITES"],str(PRODUCTION_PROFILE["writes"]))


if __name__=="__main__":
    unittest.main()
