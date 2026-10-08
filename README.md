# HoloViewer

**Unofficial Hololive fan viewer — public deployment smoke preview, not a functional product release.**

This minimal Streamlit application is an isolated preview for testing hosting and presentation. It is **not affiliated with, endorsed by, or operated by COVER Corp., hololive production, YouTube, or Google**.

## What this preview does

- Shows three navigation tabs: 首頁, 直播同步, 同時視聽.
- If a separately reviewed public snapshot is published, the homepage may display its sanitized YouTube video titles and links. **No snapshot is currently shipped.**
- 直播同步 and 同時視聽 are disabled placeholders. No multi-stream functionality exists in this repo.

This repository has **no PTT Collector, backfill, admin services, PTT login, private database, authentication credentials, Google API key, embedded YouTube player, assets, recordings or third-party transcripts**. It was initialized using an explicit small-file copy; **no private upstream Git history was copied**.

## Deploy

Repository `physicsdog0505/HoloViewer`, branch `main`, entrypoint `app.py`, no Secrets. Python 3.11 was used for initial isolated test CI.

**Privacy warning:** Publishing this GitHub repo and deploying it to Streamlit Community Cloud makes the smoke code (and potentially the hosted page) available publicly. Never upload private data or deployment secrets. Do not confuse this preview with a restricted-access staging environment.

## Contributions, copyright and references

This preview has not adopted an open-source license yet. Publishing code on GitHub does not itself grant an open-source redistribution license. Any later licensing decision must be explicit and must separately cover only code we own or can license. Consult [REFERENCES.md](REFERENCES.md) for frameworks and applicable third-party policies. Attribution alone is not copyright permission.

## Release gate

The private engineering repository remains the canonical source. Publishing this minimal scaffold **does not authorize** publishing more private code, integrating API keys, enabling Watchalong or Live Sync, or automatic sync from the private repo. Future additions require independent security, dependency, permissions, source/rights, and user-acceptance review.

## Phase 1A deployment verification and rollback

This is a smoke verification only; it does **not** publish live data or enable unfinished features.

1. Verify the public page renders all three tabs with placeholders, and no secrets are required.
2. Review public PR #3 and check the `Public smoke release review` CI success. It checks Python compilation, strict import/asset boundaries, dependencies, and local Streamlit `/_stcore/health`.
3. **Only after human approval**, merge this small PR to `main`. Streamlit Community Cloud should follow `main` automatically.
4. Open https://holoviewer.streamlit.app, refresh and look for `Deployment check: public-smoke-v2`. Record actual observed result and time. GitHub CI success alone does not prove cloud redeployment.
5. For rollback verification, open a *separate revert PR* removing only the marker (or revert this exact deployment commit), run CI, obtain human merge approval, and confirm the marker disappears after deployment. Do not force-push or expose private files.
6. Keep screenshots/logs with secrets redacted. If the page fails, check Streamlit Cloud app logs for entrypoint `app.py`, Python 3.11 and requirements resolution.

The app has no runtime dependence on the user's Mac mini, private repository or private SQLite. Public site filesystem is ephemeral; any future snapshot must have a separate persistent origin. GitHub Release Assets remain a future **candidate** under #290–#292; not a blocker for Phase 1A.
