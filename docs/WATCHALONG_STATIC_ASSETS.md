# Watchalong Static Assets

Dedicated public static-assets target for Watchalong read-only data.

- Worker: `holoviewer-watchalong-static-assets`
- Public origin: `https://holoviewer-watchalong-static-assets.singlebagel.workers.dev`
- Asset tree: `watchalong-static/data/watchalong/**`
- Frontend consumer data must not be packaged by `holoviewer-public`.
- Production deploy/rollback is Owner-local only. GitHub Actions/CI must not deploy this target.

The manifest and event JSON bytes remain exporter-canonical. The dedicated origin preserves the existing public paths under `/data/watchalong/**`.


## Release ownership

Watchalong manifest inventory, event-file SHA validation, CORS, and live readback belong to the dedicated Watchalong owner-local release path only.

Generic `holoviewer-public` frontend releases verify only that the frontend consumer remains pointed at this dedicated origin and that `site/data/watchalong/**` is absent from the frontend candidate. Frontend releases must not fetch or gate on the current Watchalong event inventory.
