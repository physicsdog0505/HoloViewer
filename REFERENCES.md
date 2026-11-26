# HoloViewer / HoloDocchi References

This file lists external documentation and policy references relevant to the
public project. It is not a statement that every referenced service endorses
HoloDocchi, and it does not grant rights to third-party content.

## Project status

HoloDocchi is an active unofficial fan project. The repository is no longer
only the original Streamlit deployment smoke preview.

The current public frontend is the Cloudflare-hosted `site/**` application.
The root-level Streamlit `app.py` remains only as legacy smoke-preview
lineage.

## COVER Corp. / hololive production

- Derivative Works Guidelines:
  https://hololivepro.com/en/terms/

These guidelines should be reviewed when project behavior, branding, artwork,
fan content, or presentation changes.

## YouTube / Google

- YouTube API Services Terms of Service:
  https://developers.google.com/youtube/terms/api-services-terms-of-service
- YouTube API Services Developer Policies:
  https://developers.google.com/youtube/terms/developer-policies
- YouTube Embedded Players and Player Parameters:
  https://developers.google.com/youtube/player_parameters
- Required Minimum Functionality:
  https://developers.google.com/youtube/terms/required-minimum-functionality

HoloDocchi primarily uses YouTube's embedded player for playback and does not
claim ownership of YouTube-hosted audiovisual works.

## Cloudflare

The public frontend and multiple static publication surfaces use Cloudflare
Workers / static asset deployment.

- Cloudflare Workers documentation:
  https://developers.cloudflare.com/workers/
- Static assets:
  https://developers.cloudflare.com/workers/static-assets/
- Wrangler:
  https://developers.cloudflare.com/workers/wrangler/

## Streamlit

Streamlit remains relevant to the repository's original smoke-preview lineage,
but it is not the current HoloDocchi production frontend architecture.

- Streamlit:
  https://streamlit.io/
- Documentation:
  https://docs.streamlit.io/
- License:
  https://github.com/streamlit/streamlit/blob/develop/LICENSE

## PTT

PTT articles and pushes are third-party/user-generated content. Their
appearance in a read-only HoloDocchi interface does not transfer ownership to
this project and does not make that content MIT-licensed.

## Repository licensing

Project-owned code eligible for relicensing is released under the MIT License.

See:

- `LICENSE`
- `DATA_SOURCES_AND_ATTRIBUTION.md`
- `THIRD_PARTY_NOTICES.md`

The MIT License does not override third-party copyrights, trademarks, platform
terms, database rights, or other applicable rights.

## Maintenance note

External terms and documentation can change. Contributors working on an
integration should verify the current version of the relevant upstream policy
rather than relying only on this reference list.
