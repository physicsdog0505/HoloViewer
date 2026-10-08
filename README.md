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
