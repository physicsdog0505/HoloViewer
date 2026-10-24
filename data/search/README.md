# HoloDocchi Search Alias Seed V1

This branch contains the first owner-reviewable fan-vocabulary seed for History Search.

## Files

- `data/search/member_aliases.v1.json` — canonical seed data.
- This README — implementation and review notes for #50.

## Current coverage

- 69 member identities from the current frontend `TIME_HUB_MEMBERS` registry.
- 392 aliases.
- 0 strong-alias collisions after NFKC + case-fold audit.
- Strong aliases may resolve directly to a member.
- Weak aliases are ranking hints only and must not uniquely resolve a member.

This is intentionally a **V1 seed**, not a claim of complete historical coverage. Before #50 marks alias coverage complete, it must reconcile the 69 frontend identities with the YouTube Static manifest `channel_indexes`, because History includes channels that may no longer be in the current frontend member registry.

## Examples

### Roboco

Canonical channel:
`UCDqI2jOz0weumE8s7paEk6g`

Strong aliases include:
- ロボ子さん
- ロボ子
- Roboco
- Roboco-san
- 蘿蔔子 / 萝卜子
- 蘿蔔 / 萝卜
- RBC
- 二姐 / 二姊

### Choco

Canonical channel:
`UC1suqwovbL1kzsoaZgFZLKg`

Strong aliases include:
- 癒月ちょこ
- Yuzuki Choco
- Choco
- 癒月巧可
- 巧可
- 巧可老師 / 巧可老师
- Choco-sensei

Weak aliases:
- 老師 / 老师

### Other high-value Taiwan-community aliases already seeded

- 35 → さくらみこ
- 486 / 鴨鴨 / 鴨子 → 大空スバル
- 船長 / 阿船 → 宝鐘マリン
- 團長 → 白銀ノエル
- 兔子 / 兔兔 → 兎田ぺこら
- 狼媽 → 大神ミオ
- 飯糰貓 → 猫又おかゆ
- 麵包狗 → 戌神ころね
- TMT → 常闇トワ
- 446 → 獅白ぼたん
- 座長 → 尾丸ポルカ
- 山田 → ラプラス・ダークネス
- 61 → 鷹嶺ルイ
- 博士 → 博衣こより
- 虎鯨 → 沙花叉クロヱ

## Normalization contract

Resolver should normalize query and alias values with:

1. Unicode NFKC.
2. Case-insensitive Latin matching.
3. Collapsed whitespace.
4. Punctuation as token boundaries.
5. Preserve CJK characters; do not romanize CJK automatically.

Do **not** use fuzzy edit-distance matching in V1. This corpus is intended to encode community vocabulary explicitly rather than guess arbitrary spellings.

## Query intent contract

### One resolved member

`roboco`

→ resolve to Roboco and search that member's History.

### Two or more resolved members

`roboco choco`

→ resolve to two canonical member IDs and treat this as a **multi-member relevance query**, not a collab declaration.

Ranking order:

1. Results with search evidence for all requested members.
2. Results with search evidence for one requested member as fallback.

Search evidence in V1 comes from stable host `channel_id` plus title/channel metadata alias matches.

Important: matching multiple member names in title/metadata does **not** create canonical collab truth and must not add a collab badge. Existing collab materialization remains a separate authority used only by the existing collab presentation path.

### Member + free text

`roboco minecraft`

→ member constraint = Roboco, free-text keyword = minecraft.

### Multiple members + free text

`roboco choco minecraft`

→ resolve Roboco + Choco as requested members, require the free-text keyword `minecraft`, and rank results related to both members ahead of one-member fallback results.

## Owner CRUD requirements for #50

8501 should expose a Search Aliases admin page.

Minimum operations:

- add alias
- edit alias
- enable / disable alias
- change strong / weak
- change member assignment
- add note/source
- inspect normalized value
- warn on strong-alias collision before save

Do not hard-delete by default. Disabled aliases should remain auditable.

Suggested fields:

```json
{
  "value": "二姐",
  "type": "alias",
  "strength": "strong",
  "source": "owner",
  "enabled": true,
  "note": ""
}
```

Community seed aliases must not overwrite later Owner edits.

## Public boundary

Recommended flow:

```
8501 Owner UI
  -> owner-local canonical alias store
  -> validate/build
  -> public read-only alias artifact
  -> Production History Search resolver
```

Production must remain read-only. No D1 writer is required for alias editing.

## Research basis

V1 uses current canonical member identities from HoloViewer and conservative Taiwan-community vocabulary observed in PTT / Bahamut usage. Examples include 35, 486, 446, 61, TMT, 蘿蔔子, 巧可老師, 船長, 兔子 and other long-running community terms.

Research references are recorded inside `member_aliases.v1.json`.

## Known V1 gap

The seed is based on the current 69-identity frontend member registry. Historical/graduated/former channels that still exist in YouTube Static History must be added after #50 reconciles against `manifest.channel_indexes`.

Do not silently treat a missing alias as “no such member”; unresolved text must continue through ordinary text search.
