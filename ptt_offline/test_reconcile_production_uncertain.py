import unittest
from ptt_offline.reconcile_production_uncertain import parse_marker

class ReconcileProductionTests(unittest.TestCase):
    def test_parse_short_d1_marker(self):
        out="│ PTT_RECON_PUSHES=25 │\n│ PTT_RECON_EVIDENCE=25 │"
        self.assertEqual(parse_marker(out,"PTT_RECON_PUSHES"),25)
        self.assertEqual(parse_marker(out,"PTT_RECON_EVIDENCE"),25)

    def test_missing_marker_fails_closed(self):
        with self.assertRaises(SystemExit):
            parse_marker("wrangler output without receipt","PTT_RECON_PUSHES")

if __name__=="__main__":
    unittest.main()
