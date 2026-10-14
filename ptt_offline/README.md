# Issue #48 — PTT offline contract slice

**Status: Draft, offline fixtures only. Not a Public API / production implementation.**

This directory is a standalone Python standard-library adapter and adversarial test suite. It never reads SQLite, PTT, network, Cloudflare, or runtime configuration. It does not modify `site/**`, Collector, Publisher, 4174, 8501, or Worker/D1.

Run from repository root:

```bash
python -B -m unittest -v ptt_offline.test_public_today_contract
```

### Proposed contract / non-authoritative

- Selected Taipei date merges explicit AID set; caller must provide real thread discovery/identity evidence later.
- Initial read returns last 300 pushes; bounded `read_after_key` detects absent anchor as history gap. Ordering uses source timestamp, AID, source line and ID.
- Synthetic relay pages use cursor per AID (not source_line/floor), cap each page at 200 and 512 KiB, reject replays, cross-AID rows, expired cursor and retention gaps.
- Snapshot and relay de-duplicate using a digest based on AID, absolute source line, author, UTC timestamp and content. **This digest's exact wire/hash encoding is a PROPOSAL, not certified byte parity with private #311.** Before production, reuse #311's vetted canonical implementation or add strict cross-repo vectors.
- Collector rows take precedence over matching Web rows; display floor is never synthesized.
- Stale fetch preserves last good rows; rollover creates only a fresh PTT adapter state, never manipulates player.
- The History fixture validator accepts only explicitly marked synthetic accepted evidence **bound to requested day and exact AID set**. It cannot verify cryptographic provenance; production must use trusted signed/owner-controlled manifests. Checksum or caller `complete` alone is insufficient.
- Relay retained-row gap remains `partial` after a newer snapshot; no coverage reset exists.

### Required follow-up gates (not part of PR)

1. Exact-head Python focused test receipt and independent review.
2. Match against latest accepted 4174 SHA, not only historical `cab0adb51...`, plus private #311/#312/#313/#315/#328 and Public #12/#19 exact revisions.
3. Confirm #311 byte-for-byte canonical identity, initial `tail=1` semantics in **actual** wire adapter, source-generation/range→ACK proof, and public-history accepted completeness authority.
4. #317 real G3 HOLD remains. No release, Worker/D1 operation, real Publisher run, Cloudflare billing or PTT data access authorized.
