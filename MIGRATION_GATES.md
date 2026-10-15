# 8788 Full 4174 Migration Gates

Authoritative product source:

- repository: `physicsdog0505/Hololive-PTT-Viewer`
- commit: `a144bb378a8bdd772faa867d608c1e7491253883`
- accepted local branch: `feat/4174-history-day-391`
- vendored root: `vendor/4174-a144bb3/`

## Current allowed work

Only **Phase A + Phase B** are allowed on this branch right now.

### Phase A — complete source snapshot

- Vendor only files justified by the pinned 4174 dependency graph.
- Do not rewrite product behavior.
- Keep DBs, caches, credentials, generated/runtime data, and owner-local artifacts out.
- Required accepted roots:
  - `client_app.py`
  - `client_custom_view.py`
  - `client_history.py`
  - `client_home.py`
  - `client_ptt_today.py`
  - `client_ui_shell.py`
  - `client_watchalong.py`
  - `shared_viewing_core.py`
- Required static/runtime assets include:
  - `public/ptt_timeline.js`
  - `public/ptt_player_adapter.js`
  - `public/ptt_worker_adapter.js`
  - `hololive_channels.prototype.json`

### Phase B — provenance / anti-contamination

Every vendored product file must be recorded in
`provenance/4174-source-manifest.json` with:

- relative path
- source repository
- source commit
- source blob SHA
- role

Run:

```sh
python3 tools/verify_4174_snapshot.py
```

The verifier must fail closed when:

- a product blob differs from pinned 4174;
- a required local dependency is absent;
- an unmanifested product file appears;
- a required static path escapes the vendored snapshot;
- old Public product files are present;
- migration runs from either failed branch;
- Phase C/E launcher/platform artifacts are introduced early.

## Explicitly forbidden migration sources

These branches are historical failed experiments only:

- `dev/8788-parity`
- `dev/8788-clean-transplant`

No product HTML/CSS/JS/Python logic may be cherry-picked from them.

## Blocked until later Review checkpoints

### Phase C — local 8788 launcher/runtime isolation

**Blocked.** Do not add the 8788 launcher yet.

### Phase D — runtime/UI parity

**Blocked.** Do not claim visual/runtime parity from source equivalence.

### Phase E — Cloudflare compatibility

**Blocked.** No Cloudflare/platform implementation yet.

When Phase E is eventually unblocked, platform code may handle only:

- hosting/static delivery
- route mapping
- API transport/proxy
- CSP/CORS
- Worker/runtime compatibility
- environment/config injection
- service endpoints required by accepted 4174 behavior

It must not reimplement or alter:

- player lifecycle or controls
- multi-view layout/selection
- Custom View behavior
- Watchalong behavior
- immersive/fullscreen/ESC
- audio behavior
- PTT UI/timeline/player behavior
- Home UI
- History UI
- navigation/layout/CSS geometry

If the platform cannot preserve accepted 4174 behavior, stop and report the incompatibility.

## Checkpoint order

1. SOURCE SNAPSHOT COMPLETE
2. RUNTIME ISOLATED
3. 4174 PARITY
4. PLATFORM ADAPTER

Do not skip checkpoints.
