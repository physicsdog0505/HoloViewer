# Snapshot Adapter and Reconciliation Evidence

## Inputs

`data_lifecycle/adapters.py` consumes JSON only. It does not open SQLite, call
an API, use Wrangler, fetch R2, or import any #47/#48 writer.

YouTube input:

- versioned roster `{version, channels[{id}]}` from the #47 contract;
- `public-consumer-v1` / `public-today-v1` `streams`;
- `public-history-import-preview-v1` rows from PR #140;
- optional independently verified daily expected-video envelope;
- explicit `sanitized: true` target snapshot.

PTT input:

- PR #55 day-stage `{day, rows}` preserving day, AID, source line, `push_id`
  and `source_record_key`;
- `ptt-r2-archive-v1` manifest from PR #135;
- article/source-line coverage evidence and sanitized checkpoint summary;
- optional independently verified daily expected-AID envelope;
- explicit `sanitized: true` target snapshot.

The current #47/#48 contracts do not independently prove their complete daily
expected sets. Without the optional authority envelope the inventory is
`UNKNOWN`; the adapter records the exact gap instead of guessing. An envelope
cannot self-assert authority: the embedding caller must supply a verifier.
The CLI supplies none and therefore fails closed to `UNKNOWN`.

## Contract-derived sanitized evidence

No production snapshot was provided or accessed. The committed snapshots are
small, synthetic/sanitized extracts derived from existing branch test vectors:

- YouTube `2026-10-15`: video `8pF4qHcshDc` and exact timestamps from PR #140's
  History Preview test fixture.
- PTT `2026-10-01`: two pushes and hourly archive semantics from PR #135's R2
  exporter fixture. One legal empty-content push is retained.

The test-only authority envelope is explicitly named
`contract-fixture-authority-v1`; it is not production authority.

## Dry-run results

| Scenario | Result |
|---|---|
| YouTube fixture with explicit test verifier, empty sanitized target | `COMPLETE`; `8pF4qHcshDc → INSERT`; writes 0 |
| PTT fixture with explicit test verifier, empty sanitized target | `COMPLETE`; lines 10 and 11 → `INSERT`; writes 0 |
| Source incomplete | Added expected `missingVid1`; `REPAIR_NEEDED`, missing ID reported |
| Revision conflict | Newer sanitized target for `8pF4qHcshDc`; `CONFLICT/target-newer-than-source` |
| CLI/existing contracts without injected verifier | `UNKNOWN`, never `COMPLETE` |

Commands:

```sh
python3 -m data_lifecycle.cli --contract-export --date 2026-10-15 \
  --snapshot fixtures/data-lifecycle/youtube-2026-10-15.sanitized.json \
  --json-out /tmp/youtube-reconciliation.json \
  --markdown-out /tmp/youtube-reconciliation.md

python3 -m data_lifecycle.cli --contract-export --date 2026-10-01 \
  --snapshot fixtures/data-lifecycle/ptt-2026-10-01.sanitized.json \
  --json-out /tmp/ptt-reconciliation.json \
  --markdown-out /tmp/ptt-reconciliation.md
```

Generated reports remain temporary because they duplicate fixture data. The
source fixtures and assertions are committed and reproducible. These CLI
commands intentionally report `UNKNOWN`; the `COMPLETE` fixture scenarios are
exercised by `test_snapshot_integration.py` with a verifier restricted to the
named offline-test issuer/version.

## Contract gaps requiring #47/#48 ownership

- #47: emit a reviewed daily expected-video authority/version, or explicitly
  define why exhaustive daily video completeness cannot be asserted.
- #48: emit reviewed expected AIDs plus normalized article-line classification
  evidence. R2 `COMPLETE` alone proves exporter coverage, not the expected
  thread set independently.
- Target snapshot owner: define a versioned sanitized D1/R2 export envelope
  with observation time, revision semantics and content hash. The adapter will
  not infer these from live endpoints.
