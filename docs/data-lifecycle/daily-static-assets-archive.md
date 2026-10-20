# Issue /160 — Daily finalized PTT → Workers Static Assets

Status: source/offline/runtime seam only. Production mutation is not authorized.

## Ownership boundary

/160 consumes only `holoviewer-ptt-daily-finalization-v1` receipts whose:

- `state == VERIFIED_COMPLETE`
- `archive_ready == true`
- expected-AID authority is verified and bound to the exact Taipei day
- receipt is sanitized and content-bound by `evidence_digest`

`UNKNOWN`, `REPAIR_NEEDED`, and `CONFLICT` fail closed. /160 does not infer
completeness, repair PTT, restart Collector/Publisher, log in, write D1, enable R2,
or operate 8501.

## Mapping

Finalization receipt → daily package:

- `day` → `taipei_day`
- `expected_set.expected_aids` → immutable package thread scope
- `expected_set.authority` → package expected-AID authority
- `evidence_digest` → `finalization_evidence_digest`
- injected finalized source snapshot → `source_revision` + `source_hash`
- canonical JSON objects → immutable content-addressed Static Assets objects

Daily object key:

`ptt/v1/history/<taipei-day>/<source-hash-prefix>/<logical-key>.json`

Daily manifest key:

`ptt/v1/manifests/daily/<taipei-day>/<manifest-digest>.json`

A legal repair revision therefore gets a new source hash and a new manifest
identity. Existing historical bytes are never silently overwritten.

## Manifest / object identity

Package schema:

`holoviewer-ptt-daily-static-package-v1`

Manifest digest is SHA-256 over exact canonical manifest bytes. Object SHA-256 is
computed over exact canonical JSON bytes served by Static Assets.

The existing Archive contract remains authoritative:

- `job_id`
- `source_revision`
- `source_hash`
- `manifest.digest`
- readback `snapshot_id`

remain distinct identities.

Canonical archive object identity remains:

`manifest_digest + object_key + canonical_object_sha256`

## Runtime seam

`prepare_static_assets_delivery()` produces
`holoviewer-static-assets-delivery-plan-v1` with:

- `production_execution=false`
- `deploy_authorized=false`
- Workers Static Assets target only
- exact manifest/object set for one Taipei day

It executes no subprocess and no Cloudflare API.

`verify_http_readback()` accepts an injected byte-fetch transport. A future
approved Production runtime may bind a real HTTP client, but the verifier itself
requires independent re-fetch of:

1. exact manifest bytes and digest
2. exact object set
3. every canonical object SHA and byte length
4. exact one-day coverage scope

It then emits the already-reviewed
`holoviewer-archive-readback-receipt-v1`.

`build_archive_delivery_evidence()` emits the already-reviewed
`holoviewer-archive-job-evidence-v1`.

Source completeness, package build status, delivery job status, and independent
readback verification stay separate. A failed deploy does not downgrade a
VERIFIED_COMPLETE source day. A successful deploy with failed readback remains
unverified.

## Idempotency

Rebuilding the same day/revision/hash with identical bytes is a no-op. If the
same immutable object path already exists with different bytes, the build fails
closed.

Only the target day paths are created. Unrelated historical day objects are
untouched.

## Focused acceptance cases

`ptt_offline.test_daily_static_assets_archive` covers:

- VERIFIED_COMPLETE → package build
- UNKNOWN → fail closed
- REPAIR_NEEDED → fail closed
- package complete + delivery failed → source completeness remains COMPLETE
- delivery succeeded + readback/hash failed → job remains unverified
- same package/job retry is idempotent
- unrelated historical day remains byte-identical
- manifest digest mismatch fails closed
- object SHA mismatch fails closed
- rows outside verified day/AID scope are rejected

## Production gate

Not implemented/authorized in this slice:

- 07:30 scheduler activation
- binding to the real /55 receipt source
- real finalized source snapshot loader
- real Cloudflare/Workers Static Assets deploy command
- Production HTTP endpoint binding
- Production secrets
- merge/deploy

Those require /45 independent review and Owner-local Production gate.
