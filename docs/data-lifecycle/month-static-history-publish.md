# Consolidated month → Workers Static Assets adapter (#160)

Status: offline implementation and owner-local evidence only. Static Assets
deployment, Production mutation, R2, D1, PTT access and scheduling remain
unauthorized.

## Narrow lifecycle

`month_static_publish.py` accepts one completed-month SQLite and its accepted
audit. Before reading rows it verifies both exact SHA-256 values. It then checks
the audit and the SQLite independently: month identity, article and push counts,
`quick_check`, foreign keys, duplicate AIDs, per-article COMPLETE state, and the
declared/parsed/stored/contiguous-floor rule for Web sources.

The stages remain separate:

1. **source completeness** — exact-SHA consolidated month evidence;
2. **package build** — immutable canonical objects, provenance, manifest and
   month registration;
3. **delivery attempt** — currently only an owner-local filesystem seam;
4. **HTTP readback** — rereads the registration, manifest, provenance and every
   object and emits `holoviewer-archive-readback-receipt-v1`;
5. **job evidence** — emits `holoviewer-archive-job-evidence-v1` for PR #147.

A failed or missing delivery never changes source COMPLETE. A successful
delivery never implies source completeness without the accepted source audit.

## Identity and immutable layout

Registration key:

`ptt/v1/registrations/YYYY-MM.json`

Registration identity canonically binds:

- source SQLite SHA-256 and accepted audit SHA-256;
- ordered article set and per-article logical/source hashes;
- provenance object hash;
- Archive v1 manifest digest;
- every object key and canonical object SHA-256.

The manifest retains the `ptt-r2-archive-v1` object schema used by PR #135.
Objects use the following Static Assets namespace:

`ptt/v1/months/YYYY-MM/chunks/YYYY/MM/DD/HH00.json`

The source-month namespace is intentional. A night thread can cross a month
boundary, so independently accepted adjacent months can contain pushes in the
same UTC hour. A global hourly key would allow one completed month to overwrite
another. The registration and manifest are the canonical lookup authority.

Raw rows retain the real Collector `source_line`. Web rows use
`source_line: null`, `source_locator_kind: web_floor` and
`floor_quality: verified-web-floor`; a Web floor is never represented as a
Collector source line. Public provenance retains only the source basename and
hash, never the owner-local absolute path.

An identical retry is a no-op. The same month with a different registration
identity, or any target object with different bytes, fails before any writes.
Chunks and provenance are copied first; manifest and registration are committed
last. This is a delivery ordering boundary, not a Production deploy mechanism.

## Owner-local one-command proof

```text
python3 -m ptt_offline.month_static_publish run-local \
  --month YYYY-MM \
  --sqlite /owner/path/month.sqlite3 \
  --sqlite-sha256 EXPECTED_SQLITE_SHA256 \
  --audit /owner/path/month.audit.json \
  --audit-sha256 EXPECTED_AUDIT_SHA256 \
  --article-count EXPECTED_ARTICLES \
  --out /private/tmp/month-package \
  --target-root /private/tmp/static-assets-readback \
  --observed-at 2026-10-21T12:00:00Z
```

The command builds, copies to an owner-local immutable target, serves only that
temporary target on localhost, performs full HTTP readback, and writes build,
delivery, readback and archive-job receipts. It contains no Cloudflare client,
credential lookup or Production target implementation.

## Production gate and rollback boundary

Production remains blocked until #45 reviews and explicitly approves the exact
registration identities, Static Assets capacity/deploy process, public reader
adapter, target URL and post-deploy readback. A future deployer must upload
immutable month objects first and publish manifest/registration last. Before the
registration becomes public, abort leaves no discoverable month. After it is
public, rollback must restore the previous reviewed Static Assets deployment;
objects and registrations must never be overwritten in place.

Production mutation: **NO**

R2 execution: **NO**

Scheduler enabled: **NO**
