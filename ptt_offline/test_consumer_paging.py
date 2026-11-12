"""Issue #48 consumer-facing paging regressions (offline synthetic only)."""
import unittest

from ptt_offline.public_today_contract import (
    ContractError, PttConsumerReader, SyntheticPttProvider,
)


def row(n, aid="A1"):
    return {
        "aid": aid, "source_line": n, "floor": None,
        "author": "tester", "content": f"message-{n}",
        "occurred_at": "2026-10-15T03:00:00+08:00",
        "origin": "collector",
    }


class ConsumerPagingTests(unittest.TestCase):
    def provider(self):
        return SyntheticPttProvider(
            {"2026-10-15": {"A1", "A2"}, "2026-10-16": {"B1"}},
            snapshots={
                "2026-10-15": [row(i, "A1" if i % 2 else "A2") for i in range(1, 8)],
                "2026-10-16": [row(1, "B1")],
            },
        )

    def test_real_page_two_three_and_terminal(self):
        reader = PttConsumerReader(self.provider())
        first = reader.read_history("2026-10-15", {"limit": 3})
        self.assertEqual([x["source_line"] for x in first.pushes], [1, 3, 5])
        self.assertTrue(first.page["has_more"])
        cursor1 = first.page["next_checkpoint"]
        self.assertNotEqual(cursor1, first.checkpoint)
        second = reader.read_history("2026-10-15", {"limit": 3, "checkpoint": cursor1})
        self.assertEqual([x["source_line"] for x in second.pushes], [7, 2, 4])
        self.assertTrue(second.page["has_more"])
        third = reader.read_history("2026-10-15", {"limit": 3, "checkpoint": second.page["next_checkpoint"]})
        self.assertEqual([x["source_line"] for x in third.pushes], [6])
        self.assertFalse(third.page["has_more"])
        self.assertIsNone(third.page["next_checkpoint"])
        self.assertEqual(len({x["push_id"] for x in first.pushes + second.pushes + third.pushes}), 7)

    def test_unknown_token_rejected(self):
        reader = PttConsumerReader(self.provider())
        with self.assertRaises(ContractError):
            reader.read_history("2026-10-15", {"checkpoint": "unrecognized"})

    def test_foreign_day_rejected(self):
        reader = PttConsumerReader(self.provider())
        token = reader.read_history("2026-10-15", {"limit": 2}).page["next_checkpoint"]
        with self.assertRaises(ContractError):
            reader.read_history("2026-10-16", {"checkpoint": token})

    def test_snapshot_mutation_invalidates_continuation(self):
        provider = self.provider()
        reader = PttConsumerReader(provider)
        token = reader.read_history("2026-10-15", {"limit": 2}).page["next_checkpoint"]
        provider.snapshots["2026-10-15"].append(row(8))
        with self.assertRaises(ContractError):
            reader.read_history("2026-10-15", {"checkpoint": token})

    def test_invalid_limit_and_wrong_token_shape(self):
        reader = PttConsumerReader(self.provider())
        for limit in (0, 201, True, "2"):
            with self.assertRaises(ContractError):
                reader.read_history("2026-10-15", {"limit": limit})
        with self.assertRaises(ContractError):
            reader.read_history("2026-10-15", {"checkpoint": 10})


if __name__ == "__main__":
    unittest.main()
