# Public local acceptance workflow

Purpose: validate the transplanted 4174 viewer on the Mac before spending GitHub Actions minutes or deploying production.

## Rules

- 4174 remains the source of truth.
- Do not use production as the first test environment.
- Accumulate related fixes locally.
- Run local preflight and browser acceptance first.
- Open one PR only at a meaningful checkpoint.
- Run one CI for that checkpoint.
- Production deployment is manual-only.

## Start the local Public runtime

```sh
cd ~/Downloads/HoloViewer
sh scripts/start_public_local.sh
```

Default URL:

```text
http://127.0.0.1:8788/
```

Change the port if needed:

```sh
HOLOVIEWER_PUBLIC_LOCAL_PORT=8790 sh scripts/start_public_local.sh
```

This uses the repository's real `cloudflare/wrangler.json` and real `site/**` assets.

## Run local preflight without deployment

```sh
sh scripts/check_public_local.sh
```

## Browser acceptance order

1. Custom view -> one video -> normal mode.
2. Enter immersive -> press ESC -> confirm full restoration.
3. Two videos -> Equal.
4. Two videos -> Focus A/B.
5. Enter/exit immersive in two-video Equal and Focus.
6. PTT panel mount and scroll.
7. Re-enter single/multi within the same SPA session to catch YouTube API lifecycle bugs.

Only after these pass locally should a PR/CI/deploy be used.
