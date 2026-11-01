# Daily Digest Return Automation v2

## Goal

Close the post-Gemini half of the Daily Digest pipeline without introducing a second content authority or unattended Drive credentials.

```text
local catalog
  -> deterministic input manifest
  -> approved raw-byte Drive transport
  -> Gemini research / JSON + Markdown siblings
  -> exact raw-byte return transport
  -> deterministic return ingest gate
  -> immutable source revision + normalized public candidate
  -> publication decision / deploy boundary
```

## Responsibility boundary

### Upstream producer

Owns:
- TARGET_DAY / TIMEZONE;
- exact Stream List universe;
- expected output sibling filenames;
- Drive folder target;
- run receipt.

Does not own Gemini editorial content.

### Drive transport

Transport only.

It may:
- upload the exact input manifest bytes;
- fetch the exact expected Gemini JSON / Markdown sibling bytes.

It must not:
- choose a different date;
- rename sibling outputs;
- decide whether coverage is complete;
- edit Gemini output;
- normalize content;
- decide publication.

No unattended local Drive OAuth is introduced by this contract.

### Gemini

Owns research and editorial synthesis under the canonical guideline.

It writes exactly the manifest-declared JSON + Markdown siblings.

### Return ingest

Authority:
`scripts/daily_digest_return_ingest_v2.py`

It validates:
- exact sibling filenames;
- non-empty JSON + Markdown;
- Gemini schema;
- TARGET_DAY / TIMEZONE identity;
- exact Stream List video_id order and coverage;
- optional audit total;
- normalizer acceptance.

It stages under:

```text
validation/daily-digest-v2/returns/<TARGET_DAY>/<GEMINI_JSON_SHA256>/
```

The directory is immutable by source JSON SHA. A changed Markdown sibling under the same JSON revision is a collision and must fail rather than silently overwrite.

Staged outputs:
- exact raw Gemini JSON;
- exact raw Gemini Markdown;
- normalized `<TARGET_DAY>.public-candidate.json`;
- `return.receipt.json`.

Successful status:
`READY_FOR_PUBLICATION`.

Repeated identical input:
`NO_CHANGE`.

## Publication boundary

Return ingest does not deploy and does not mutate production automatically.

Local publication authority:
`scripts/daily_digest_publish_candidate_v2.py`

The publish gate verifies the return receipt is `READY_FOR_PUBLICATION`, checks the exact candidate SHA, enforces `<TARGET_DAY>.json`, and defaults to dry-run. Only `--execute` atomically promotes the exact candidate bytes into:
`site/data/daily-digest/<TARGET_DAY>.json`

This is local artifact promotion only. Production deploy remains a separate Owner-local release boundary.

## Failure behavior

Stop without publication when:
- one sibling is missing;
- sibling filenames differ from manifest;
- schema / date / timezone mismatch;
- Stream List coverage or order differs;
- JSON is invalid;
- normalizer rejects content;
- immutable revision collision occurs.

Do not repair Gemini output in transport.

## Idempotency

The source JSON SHA is the revision identity.

Same manifest + JSON + Markdown:
- no duplicate staging;
- deterministic candidate;
- `NO_CHANGE`.

Changed JSON:
- new immutable revision directory.

Changed Markdown with identical JSON:
- fail collision so the sibling pair cannot drift silently.

## Durable evidence

Upstream run receipt must include:
- `expected_gemini_json`;
- `expected_gemini_markdown`;
- `return_transport_boundary`;
- `return_ingest_contract`;
- `return_status=AWAITING_GEMINI_OUTPUTS`.
