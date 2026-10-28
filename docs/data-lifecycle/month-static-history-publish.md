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

## Per-AID accepted-set build

`accepted_month_build.py` is the required pre-stage when one historical month
must be assembled from more than one durable source.  Its input is an explicit,
reviewed accepted-set JSON.  It SHA-pins every source file and binds exactly one
accepted source to every AID; merely finding an article in a database is never
enough to ingest it.

For the 2026/07 production candidate, the accepted set is
`ptt_offline/fixtures/history/2026-07-accepted-set.json` and enforces:

- 62 unique accepted AIDs, with no missing or extra output AID;
- 42 AIDs at or above 1,400 pushes, all from final-complete Collector Raw;
- Raw source lines exactly `1..last_source_line`, every screen page present,
  continuous screen coverage through the final line, and push/source identity;
- 20 AIDs below 1,400 pushes from the verified Web mirror, with
  declared = parsed = stored and floors exactly `1..declared`;
- the rejected legacy July artifact SHA is evidence only and is not an input.

The fresh consolidated SQLite retains Raw source lines/screens and Web body
evidence, then emits an exact audit accepted by the existing Static Assets
packager.  A typical owner-local build is:

```text
python3 -B -m ptt_offline.accepted_month_build \
  --accepted-set ptt_offline/fixtures/history/2026-07-accepted-set.json \
  --source-root /owner/history/source-batches/2025-2026 \
  --web-sqlite /owner/web-pilot/web_week_pilot_2026.sqlite3 \
  --out-sqlite /private/tmp/issue160-202607-authoritative.sqlite3 \
  --out-audit /private/tmp/issue160-202607-authoritative.audit.json
```

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

The shared Full Offline worker already serves the reviewed 2026-08 and 2026-10
packages. A Cloudflare Static Assets deploy replaces the asset set, so a July-
only directory is not a valid production input. `month_static_release.py`
creates a fail-closed union instead. The checked-in July release specification
pins the exact production 08/10 manifest bytes and the exact July source,
manifest, article-set and registration identities. It verifies every baseline
object before copying and rejects any same-key/different-byte collision.
The staging receipt also records total deployable bytes and the largest asset,
so the owner can review capacity before authorizing the Static Assets deploy.

Owner-local staging (no network mutation):

```text
python3 -B -m ptt_offline.month_static_release stage \
  --spec ptt_offline/fixtures/history/2026-07-production-release.json \
  --month-package /private/tmp/issue160-202607-package-readback-v3 \
  --baseline-public /owner/reviewed-2026-08-package/public \
  --baseline-public /owner/reviewed-2026-10-package/public \
  --out /private/tmp/issue160-202607-production-release
```

After reviewing `release-receipt.json`, the owner-only production command is
the `owner_command` recorded in that receipt. It explicitly records the local,
non-CI execution boundary. For the path above it is:

```text
OWNER_LOCAL=YES GITHUB_ACTIONS=NO CI_DEPLOY=NO npx wrangler deploy \
  --config /private/tmp/issue160-202607-production-release/wrangler.jsonc
```

The implementation never runs this command. After an owner deploys, the real
HTTP gate is:

```text
python3 -B -m ptt_offline.month_static_release verify-http \
  --spec ptt_offline/fixtures/history/2026-07-production-release.json \
  --observed-at OWNER_SUPPLIED_UTC_TIMESTAMP \
  --receipt /private/tmp/issue160-202607-production-readback.json
```

That gate rereads and hashes all 665 July objects, all preserved 08/10 objects,
the July registration/manifest/provenance identity, early/mid/late July
samples, CORS and content types, plus a negative 404. Only a PASS receipt may
be used to claim Production Published. The 2026-09 Pilot target is separate
and is neither staged nor mutated by this release.

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
