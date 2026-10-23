import unittest
from ptt_offline.capacity_probe import probe

class CapacityProbeTests(unittest.TestCase):
    def test_indexed_capacity_has_measurements_and_never_claims_real_source(self):
        first=probe(count=50)
        self.assertEqual(first["rows"],50)
        self.assertEqual(first["mode"],"SYNTHETIC_CAPACITY_ONLY")
        self.assertFalse(first["real_data_acceptance"])
        self.assertGreater(first["net_allocated_bytes"],0)
        self.assertGreater(first["bytes_per_1000_rows"],0)
        self.assertEqual(first["headroom_budget_bytes"],400_000_000)

    def test_bounded_probe(self):
        with self.assertRaises(ValueError):
            probe(count=10001)

if __name__=="__main__":
    unittest.main()
