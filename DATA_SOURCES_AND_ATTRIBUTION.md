# Data Sources, Publication Boundaries, and Attribution

This document complements the main README.

## Principle

HoloDocchi distinguishes project-owned software from data and content obtained
from external platforms or rights holders.

The repository's MIT license does not automatically relicense third-party data
or content.

## Main public data categories

### YouTube-derived metadata

HoloDocchi may consume or display metadata associated with YouTube videos and
channels. Playback is primarily performed through the YouTube embedded player.

YouTube-originated material remains subject to YouTube's applicable terms,
policies, APIs, and the rights of the original content owners.

### Hololive / HOLOSTARS-related material

Names, marks, characters, images, audiovisual works, and other intellectual
property associated with hololive production, HOLOSTARS, COVER Corp., or their
talents are not owned by this project merely because they are referenced by
the application.

### PTT

PTT articles and pushes are third-party/user-generated content.

HoloDocchi may normalize, index, or publish read-only representations for
viewer functionality, but does not claim ownership of the underlying text.

### Subtitle artifacts

Subtitle files may be project-generated, transformed, translated, reviewed, or
derived from source material depending on the pipeline used.

A subtitle artifact being publicly readable does not by itself mean that all
underlying source material is relicensed under MIT.

### Watchalong event data

Watchalong alignment metadata and event definitions created by the project may
be project-owned structured data, but the linked source videos and Hololive
content remain third-party works.

### Daily Digest

Daily Digest artifacts can combine project-authored summaries, structured
metadata, and references to external videos or sources.

External source material retains its original rights.

## Public vs private operational data

Public application assets may include normalized and validated artifacts needed
by the browser.

Private operational evidence may include receipts, source corpora, internal
checkpoints, local databases, credentials, and unpublished research artifacts.

The presence of public build/release code does not imply that those private
inputs must be published.

## Publication model

Where practical, HoloDocchi uses:

source -> normalize -> validate -> candidate -> release gate -> public surface

This improves provenance, rollback, determinism, and separation of concerns.

## Attribution and removal

If you believe material is incorrectly attributed, improperly included, or
should be removed, please open a GitHub issue with the relevant URL/path and a
clear description of the concern. Do not include private credentials or
sensitive personal information in a public issue.
