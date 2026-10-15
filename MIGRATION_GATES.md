# 8788 Full 4174 Migration Gates

Authoritative product source:

- repository: `physicsdog0505/Hololive-PTT-Viewer`
- commit: `a144bb378a8bdd772faa867d608c1e7491253883`
- accepted local branch: `feat/4174-history-day-391`
- vendored root: `vendor/4174-a144bb3/`

## Checkpoint status

- Checkpoint 1 — SOURCE SNAPSHOT COMPLETE: PASS by independent #68 review
- Checkpoint 2 — RUNTIME ISOLATED: IN PROGRESS
- Checkpoint 3 — 4174 PARITY: BLOCKED
- Checkpoint 4 — PLATFORM ADAPTER: BLOCKED

## Phase A/B — frozen source snapshot

The vendored product snapshot and provenance manifests remain immutable:

- `provenance/4174-source-manifest.json`
- `provenance/4174-source-module-index.json`
- `provenance/4174-dependency-closure.json`

Product files may only come from pinned private 4174 `a144bb3...`.

Explicitly forbidden migration sources:

- `dev/8788-parity`
- `dev/8788-clean-transplant`

No product HTML/CSS/JS/Python logic may be cherry-picked from them.

## Phase C — clean local launcher / runtime isolation

This is the only implementation phase currently allowed.

Required artifacts:

- `scripts/start_8788_full_4174.sh`
- `tools/run_4174_snapshot.py`

The launcher/runtime runner must:

1. run `tools/verify_4174_snapshot.py` first;
2. clear `PYTHONPATH` and disable user-site imports;
3. use `vendor/4174-a144bb3/` as immutable code/static root only;
4. use a distinct external runtime-data root (disposable by default, or explicitly supplied), never nested under `vendor/**`;
5. keep runtime-data root out of `sys.path`;
6. disable Today refresh in Checkpoint 2 isolation mode;
7. resolve local 4174 imports only under the vendored snapshot;
8. verify loaded product modules are manifest-listed;
9. verify required PTT/static assets resolve under the snapshot;
10. print startup provenance including:
   - exact migration HEAD;
   - pinned 4174 source SHA;
   - cwd;
   - Python executable;
   - `sys.path`;
   - resolved `module.__file__` for loaded product modules;
   - resolved path + SHA-256 for required static assets;
11. verify the vendored snapshot is unchanged after runtime exits;
12. fail closed on any path escape, vendor write, or unmanifested product dependency.

Checkpoint 2 is not PASS until an owner-local launch proves the runtime report and an independent review accepts it.

## Phase D — 4174 parity

**BLOCKED pending Checkpoint 2 review.**

Do not claim visual/runtime parity from source identity alone. When unblocked, verify route/state behavior against accepted 4174 with browser/DOM/computed-style evidence.

## Phase E — Cloudflare compatibility

**BLOCKED.**

No `site/**`, `cloudflare/**`, Public static shell/controller, Worker adapter, CSP/CORS integration, or production deployment work may be added yet.

When Phase E is eventually unblocked, it may handle only:

- hosting/static delivery
- route mapping
- API transport/proxy
- CSP/CORS
- Worker/runtime compatibility
- environment/config injection
- service endpoints required by accepted 4174 behavior

It must not reimplement or alter player lifecycle, multi-view, Custom View, Watchalong, immersive/fullscreen/ESC, audio, PTT UI/timeline/player, Home, History, navigation, layout, or CSS geometry.

If a platform limitation prevents accepted 4174 behavior, stop and report it.

## Offline preflight

```sh
python3 tools/verify_4174_snapshot.py
```

## Checkpoint 2 launch

```sh
sh scripts/start_8788_full_4174.sh
```

No PR, CI, deployment, parity work, or Cloudflare work belongs to this checkpoint.
