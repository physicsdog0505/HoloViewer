# 8788 Full 4174 Migration Gates

Authoritative product source:

- repository: `physicsdog0505/Hololive-PTT-Viewer`
- commit: `a144bb378a8bdd772faa867d608c1e7491253883`
- accepted local branch: `feat/4174-history-day-391`
- vendored root: `vendor/4174-a144bb3/`

## Hard rules

1. Product behavior comes only from the vendored 4174 snapshot.
2. Vendored files are immutable. Their Git blob SHA must match
   `provenance/4174-source-manifest.json`.
3. No legacy Public product tree is allowed. In particular, no `site/**`,
   legacy `cloudflare/**`, Public `app.py`, Public static shell/controller,
   or old Public smoke/parity implementation may be used as a migration source.
4. `dev/8788-parity` and `dev/8788-clean-transplant` are failed experiments
   and are forbidden as source branches.
5. The launcher must clear `PYTHONPATH`, disable user-site imports, and run
   through `tools/run_4174_snapshot.py`. Local 4174 modules must resolve under
   `vendor/4174-a144bb3/`; system/external packages may resolve only from the
   Python installation.
6. Runtime data is external to the code snapshot and must be named explicitly
   with `PTT_4174_RUNTIME_ROOT`. The launcher refuses an implicit data checkout.
7. Before launch, `tools/verify_4174_snapshot.py` must pass:
   - manifest completeness
   - Git blob identity
   - local Python import closure
   - no unmanifested vendored files
   - no legacy Public product residue
8. Cloudflare compatibility work is blocked until source/runtime parity review.
   When unblocked, it may adapt only hosting, route transport, API transport,
   CSP/CORS, and Worker runtime boundaries.
9. Cloudflare/platform code must not reimplement or alter player, multi-view,
   layout, audio, immersive/fullscreen/ESC, PTT UI, Custom View, Watchalong,
   Home, History, or other 4174 product behavior.

## Local preflight

```sh
python3 tools/verify_4174_snapshot.py
```

## Isolated 8788 launch

```sh
PTT_4174_RUNTIME_ROOT=/absolute/path/to/runtime-data \
  sh scripts/start_8788_full_4174.sh
```

No PR, CI, deployment, or Cloudflare adapter is part of this source-snapshot gate.
