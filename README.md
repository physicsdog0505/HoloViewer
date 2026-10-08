# HoloViewer

Unofficial Hololive fan viewer. **Private staging scaffold — not yet a released or feature-complete website.** Not affiliated with COVER Corp. or YouTube.

This is a deliberately isolated code repository. It does **not** include PTT Collector, backfill, administration, private SQLite databases, credentials, local runtime state or the original project's Git history.

## Current state

- `app.py`: isolated Streamlit frontend with three placeholder tabs (Home, Live Sync, Watchalong).
- `public_snapshot.py`: validates an optional reviewed read-only snapshot. No live data is present by default; missing snapshot is displayed as unavailable.
- Live Sync and Watchalong are **not enabled** in this staging package. Multi-stream is out of scope.

## Streamlit private staging

Use this repo (`physicsdog0505/HoloViewer`), branch `main`, main file `app.py`, and **no secrets**. Before giving anyone its URL, explicitly set app access to private/invite-only and verify access denial in an unauthenticated browser session. A private GitHub repository does not automatically prove the deployed website is private.

**Do not deploy** if the hosting account does not support viewer access restrictions.

## Release guardrails

Changes to publicly accessible features require security, provenance, rights and runtime review. Sources and policies belong in [REFERENCES.md](REFERENCES.md). The private upstream repository is the authoritative development source; this repo is a reviewed copy only. **No automatic synchronization or public release is configured yet.**
