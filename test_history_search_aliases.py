import json
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALIAS_PATH = ROOT / "site" / "data" / "search" / "member-aliases.v1.json"


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


class HistorySearchAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
        cls.members = cls.data["members"]
        cls.by_name = {m["canonical_name"]: m for m in cls.members}
        cls.strong = {}
        cls.weak = {}
        for member in cls.members:
            for alias in member.get("aliases", []):
                if alias.get("enabled") is False:
                    continue
                table = cls.strong if alias.get("strength") == "strong" else cls.weak
                table.setdefault(norm(alias["value"]), []).append(member)

    def assertStrong(self, alias, canonical):
        matches = self.strong.get(norm(alias), [])
        self.assertEqual([m["canonical_name"] for m in matches], [canonical])

    def test_schema_and_current_seed_coverage(self):
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["dataset"], "holodocchi-member-aliases-v1")
        self.assertEqual(len(self.members), 69)
        self.assertGreaterEqual(sum(len(m.get("aliases", [])) for m in self.members), 390)

    def test_no_strong_alias_collision(self):
        collisions = {
            alias: rows
            for alias, rows in self.strong.items()
            if len({row["channel_id"] for row in rows}) > 1
        }
        self.assertEqual(collisions, {})

    def test_high_value_taiwan_aliases(self):
        cases = {
            "RBC": "ロボ子さん",
            "二姐": "ロボ子さん",
            "蘿蔔子": "ロボ子さん",
            "巧可老師": "癒月ちょこ",
            "35": "さくらみこ",
            "486": "大空スバル",
            "船長": "宝鐘マリン",
            "團長": "白銀ノエル",
            "兔子": "兎田ぺこら",
            "TMT": "常闇トワ",
            "446": "獅白ぼたん",
            "61": "鷹嶺ルイ",
            "虎鯨": "沙花叉クロヱ",
        }
        for alias, canonical in cases.items():
            with self.subTest(alias=alias):
                self.assertStrong(alias, canonical)

    def test_choco_teacher_alone_is_weak(self):
        self.assertNotIn(norm("老師"), self.strong)
        matches = self.weak.get(norm("老師"), [])
        self.assertEqual([m["canonical_name"] for m in matches], ["癒月ちょこ"])

    def test_roboco_choco_resolve_to_distinct_channels(self):
        roboco = self.strong[norm("roboco")][0]
        choco = self.strong[norm("choco")][0]
        self.assertNotEqual(roboco["channel_id"], choco["channel_id"])
        self.assertEqual(roboco["canonical_name"], "ロボ子さん")
        self.assertEqual(choco["canonical_name"], "癒月ちょこ")


if __name__ == "__main__":
    unittest.main()
