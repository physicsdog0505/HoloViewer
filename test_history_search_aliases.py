import json
import subprocess
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALIAS_PATH = ROOT / "site" / "data" / "search" / "member-aliases.v1.json"
APP_JS = ROOT / "site" / "assets" / "app.js"


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

    def parse_query(self, query, registry=True):
        js = APP_JS.read_text(encoding="utf-8")
        names = [
            "normalizeHistorySearchText",
            "historyAliasTokens",
            "historyAliasIndex",
            "parseHistorySearchQuery",
        ]
        functions = []
        for name in names:
            start = js.index(f"function {name}(")
            next_pos = js.find("\nfunction ", start + 1)
            functions.append(js[start:] if next_pos == -1 else js[start:next_pos])
        registry_data = self.data if registry else None
        script = "\n".join(functions) + "\n" + f"""
const registry={json.dumps(registry_data, ensure_ascii=False)};
const parsed=parseHistorySearchQuery({json.dumps(query, ensure_ascii=False)},registry);
console.log(JSON.stringify({{
 members:parsed.members.map(x=>x.canonical_name),
 memberIds:[...parsed.memberIds],
 weakHints:parsed.weakHints.map(x=>({{term:x.term,member:x.member.canonical_name}})),
 keywords:parsed.keywords,
 intent:parsed.intent
}}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

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

    def test_multi_token_strong_aliases_resolve_longest_span(self):
        cases = {
            "Roboco-san": ["ロボ子さん"],
            "Yuzuki Choco": ["癒月ちょこ"],
            "Tokino Sora": ["ときのそら"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                parsed = self.parse_query(query)
                self.assertEqual(parsed["members"], expected)
                self.assertEqual(parsed["keywords"], [])

    def test_weak_alias_never_adds_canonical_member(self):
        parsed = self.parse_query("roboco 公主")
        self.assertEqual(parsed["members"], ["ロボ子さん"])
        self.assertEqual(len(parsed["memberIds"]), 1)
        self.assertEqual(
            parsed["weakHints"],
            [{"term": "公主", "member": "姫森ルーナ"}],
        )
        self.assertEqual(parsed["keywords"], ["公主"])

    def test_multi_member_query_is_relevance_not_collab_intent(self):
        parsed = self.parse_query("roboco choco")
        self.assertEqual(parsed["members"], ["ロボ子さん", "癒月ちょこ"])
        self.assertEqual(parsed["intent"], "member")
        js = APP_JS.read_text(encoding="utf-8")
        self.assertNotIn("已辨識多人搜尋", js)
        self.assertIn("優先顯示同時相關的結果", js)

    def test_alias_registry_unavailable_falls_back_to_text_terms(self):
        parsed = self.parse_query("roboco minecraft", registry=False)
        self.assertEqual(parsed["members"], [])
        self.assertEqual(parsed["memberIds"], [])
        self.assertEqual(parsed["keywords"], ["roboco", "minecraft"])
        self.assertEqual(parsed["intent"], "text")


if __name__ == "__main__":
    unittest.main()
