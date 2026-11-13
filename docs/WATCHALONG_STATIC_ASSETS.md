# Watchalong Static Assets

Dedicated public static-assets target for Watchalong read-only data.

- Worker: `holoviewer-watchalong-static-assets`
- Public origin: `https://holoviewer-watchalong-static-assets.singlebagel.workers.dev`
- Asset tree: `watchalong-static/data/watchalong/**`
- Frontend consumer data must not be packaged by `holoviewer-public`.
- Production deploy/rollback is Owner-local only. GitHub Actions/CI must not deploy this target.

The manifest and event JSON bytes remain exporter-canonical. The dedicated origin preserves the existing public paths under `/data/watchalong/**`.

## Owner-local additive release

Once a new event and its selected approved-sync authority are reviewed and
merged, release the dedicated data Worker with one command from a clean Public
checkout whose `HEAD` equals the fetched `origin/main`:

```sh
git fetch origin main

CONFIRM_WATCHALONG_RELEASE=DEPLOY \
SOURCE_ROOT=/Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer \
APPROVED_SYNC_ROOT=/path/to/clean/private-main/watchalong_approved_sync \
scripts/deploy_watchalong_static_assets_owner_local.sh release
```

The command performs one source/export/test pass, then automatically:

1. locks the active dedicated Worker version as the rollback target;
2. uploads the exact merged bytes with zero Production traffic;
3. checks Worker resource parity and confirms the candidate adds exactly one
   event without changing any existing event hash;
4. confirms Production still points to the locked baseline;
5. routes 100% to the already-verified candidate version;
6. reads back every manifest/event hash and CORS header from Production; and
7. prints the source SHA, new version, rollback version and rollback command.

If post-cutover readback fails, the script automatically routes traffic back
to the locked baseline. It never deploys the frontend Worker, API Worker, D1,
Publisher, Collector or the 8501 runtime.

This data-only path intentionally does not repeat browser screenshots when the
frontend code is unchanged. UI changes still use their own browser acceptance
and frontend release path. The older `prepare`, `deploy` and `smoke` modes stay
available for incident recovery and compatibility, but routine additive
Watchalong releases use `release` only.
