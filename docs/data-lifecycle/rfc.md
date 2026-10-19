# RFC: Unified Data Lifecycle v1

## State model

`collecting → provisional → verifying → complete` is the success path.
`repair_needed`, `retry_pending`, and `failed` are explicit side states.
Calendar close only permits `provisional`; positive completeness evidence is
required for `complete`. A complete partition may return to `verifying` after a
new revision and to `repair_needed` after a detected gap.

## Partition and identity

- Day boundaries use `Asia/Taipei`.
- A YouTube livestream belongs to the Taipei day of verified `actual_start` and
  remains in that partition across midnight. Without `actual_start`, it stays
  provisional/unconfirmed; scheduled time is not final partition authority.
- PTT articles retain their AID identity across midnight. Rows are partitioned
  by verified event day while identity is `(AID, source_line)`; day/night AIDs
  never merge. An article crossing midnight can contribute rows to two daily
  inventories without losing AID identity.
- Canonical YouTube identity is `video_id`. Canonical PTT record identity is
  `(day, AID, source_line)` for planning, preserving `push_id` and
  `source_record_key` for publisher compatibility.

## Revision and source priority

Each snapshot carries `source_version`, observation/update timestamp, integer
`revision`, and SHA-256 over canonical content. Positive provider metadata and
Collector source evidence outrank projections. Existing #47/#48 owners remain
the only production writers. Equal revision with different content is a
conflict; older source never overwrites newer target.

## Completeness

YouTube is complete only when the expected roster/set is authoritative and
available, every expected candidate has validated publisher identity and
metadata, ended rows have positive `actual_start` and `actual_end`, no duplicate
identity/revision conflict remains, and the configured late-metadata verification
window has succeeded. Missing/private/deleted/upstream failure is not `ended`.

PTT is complete only when expected AIDs are known, each AID has positive
article-start-through-final-line coverage evidence, every source line in that
coverage is classified as push or explicit non-push, source lines are unique,
and unresolved timestamp/AID/revision conflicts are absent. A push whose
content is the empty string is a valid row, not a gap.

## Idempotency, recovery, and budgets

Planning yields `INSERT`, `UPDATE`, `NOOP`, `CONFLICT`, or `REPAIR_NEEDED`.
There is no execution API. Checkpoints record pending/completed identity,
attempt counts, content-bound hashes, and traffic usage. Only exact ACKs from a
future existing owner writer may advance checkpoints. Retry uses capped
exponential backoff. Exceeding the global traffic budget fails closed before a
reservation. Unavailable upstreams produce `UNKNOWN`/`UPSTREAM_UNAVAILABLE`,
never empty-complete.

Reverification rebuilds inventory from immutable snapshots, compares hashes,
and republishes only through #47/#48 after review. Repair queues contain an
identity, reason, source/target revisions, evidence hash, attempts, and next
eligible time. They never trigger crawls or writes themselves.
