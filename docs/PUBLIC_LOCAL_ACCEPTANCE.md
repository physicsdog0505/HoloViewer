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
7. Navigate Home → Viewer → Home/PTT/History and confirm each transition loads a fresh document.
8. Reload `/custom-view/session?...` and confirm the Viewer reconstructs from URL query alone.
9. Use browser Back/Forward across Collab → Viewer and confirm the URL fully restores state.

Only after these pass locally should a PR/CI/deploy be used.


## 4174 retirement checkpoint

Owner decision (2026-10-15):

- The current Mac 4174 environment remains the temporary parity source only until the local Public runtime at `127.0.0.1:8788` reproduces the accepted 4174 UI and behavior.
- Acceptance must cover at least: single view, multi-view Equal, multi-view Focus, immersive enter/ESC exit, YouTube player lifecycle, PTT layout, full-document route transitions, Viewer reload from URL, and browser Back/Forward.
- Once the owner accepts 8788 parity, **8788 becomes the sole active development and acceptance environment for this product line.**
- At that point, 4174 is frozen as an archival reference and is no longer an active development target.
- Future fixes must be developed and accepted on the local Public runtime first, then promoted to production through one reviewed checkpoint.
- Do not reintroduce a second independently evolving 4174 implementation after retirement.
