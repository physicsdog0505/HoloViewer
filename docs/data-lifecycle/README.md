# Data Lifecycle Reconciliation — Phase 1

This directory specifies and tests an offline-only reconciliation seam across
the independently owned YouTube (#47) and PTT (#48) pipelines. It does not add
a production writer, scheduler, Cloudflare binding, deployment, or crawler.

Run the prototype with an explicit fixture snapshot:

```sh
python3 -m data_lifecycle.cli --date 2026-10-19 \
  --snapshot fixture.json --json-out report.json --markdown-out report.md
```

Every sync plan is permanently marked `dry_run: true` and `external_writes: 0`.
Production execution remains the responsibility of the reviewed #47/#48
publisher paths after a separate rollout approval.

Documents:

- [architecture-audit.md](architecture-audit.md) — verified code/Issue evidence and gaps.
- [rfc.md](rfc.md) — lifecycle, identity, completeness and recovery contract.
- [rollout.md](rollout.md) — staged production adoption gates.
