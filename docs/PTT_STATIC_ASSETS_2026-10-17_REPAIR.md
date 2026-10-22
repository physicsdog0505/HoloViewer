# 2026-10-17 historical PTT repair receipt

This receipt covers an offline-only rebuild.  No Cloudflare service, D1
database, R2 bucket, Publisher, Collector process, frontend, or secret was
changed.

## Authority and scope

- Accepted baseline: `archive-floor-only/ptt/v1/manifests/2026-10-pilot.json`
- Read-only repair source: `~/Downloads/Hololive-PTT-Viewer/hololive_ptt.sqlite3`
- Replaced Taipei coverage day: `2026-10-17`
- Preserved baseline days: `2026-10-01` through `2026-10-16`
- Required AIDs: `#1gqV-enD`, `#1gqgoKNo`, `#1gqr4ffh`

All three source articles have continuous `article_screens` evidence from
source line 1 through the terminal screen.  The accepted archive had 5,470
rows for 2026-10-17.  The repaired archive has 7,989 rows.  The 2,519 added
identities all belong to `#1gqr4ffh`, span source lines 219 through 2738, and
occur from `2026-10-17T10:46:00Z` through `2026-10-17T15:59:00Z`.

The source minute regression at `1gqr4ffh:246` is preserved and labelled as a
reviewed chronology exception.  No second values were synthesized.

## Offline receipts

- Archive objects: 376
- Archive pushes: 57,405
- Archive gzip bytes: 2,388,126
- Archive manifest SHA-256:
  `9fa61d4a489da086b7b1aeecaa4c1cee83d914b981ad6cffc7388ac6974627fc`
- Static Assets objects: 376 canonical `.json` files
- Static Assets pushes: 57,405
- Static Assets canonical bytes: 32,300,373
- Static manifest SHA-256:
  `bf252d66b03930a2b65a2bd256342b93a5c905bfe7426871d59eccc7daf455e4`
- Duplicate `source_record_key`: 0
- Duplicate `(aid, floor)`: 0
- Unknown floor: 0
- Invalid/non-minute timestamps: 0
- Baseline identities removed: 0
- Rejected articles/rows: 0/0
- 2026-10-01 through 2026-10-16 gzip objects byte-identical: PASS
- Full gzip/JSON readback, manifest SHA/count, UTC-hour bucket, Taipei day,
  monotonic order, and canonical Static Assets readback: PASS

The 10/17 objects from `0000` through `0900` change only because their day
coverage metadata is upgraded from PARTIAL to COMPLETE.  `1000` gains 164
rows.  New objects are created for `1100` through `1500`.

## Persistent local artifacts

- `~/Documents/HoloViewer-Historical/static-assets-pilot-review-20261018/artifacts/archive-repaired-through-20261017`
- `~/Documents/HoloViewer-Historical/static-assets-pilot-review-20261018/artifacts/static-package-repaired-through-20261017`

The preserved `repair-spec.json`, `audit.json`, and `static-audit.json` make
the rebuild and its verification traceable.  Deployment was intentionally not
performed.
