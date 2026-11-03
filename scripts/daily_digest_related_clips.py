from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

KIND = "holodocchi.daily_digest.related_clips"
SCHEMA_VERSION = 1
PROVIDER = "holodex"
API_BASE = "https://holodex.net/api/v2/videos"
LEGACY_DEFAULT_LOCALE = "zh-TW"


class ResolverError(RuntimeError):
    pass


def canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _ordered_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        video_id = _clean(item)
        if video_id and video_id not in seen:
            seen.add(video_id)
            out.append(video_id)
    return out


def normalize_language(value: Any) -> str:
    raw = _clean(value).replace("_", "-")
    if not raw:
        return ""
    parts = raw.split("-")
    language = parts[0].lower()
    if len(parts) == 1:
        return language
    rest: list[str] = []
    for part in parts[1:]:
        if len(part) == 4:
            rest.append(part.title())
        elif len(part) in (2, 3):
            rest.append(part.upper())
        else:
            rest.append(part)
    return "-".join([language, *rest])


def language_family(value: Any) -> str:
    normalized = normalize_language(value)
    return normalized.split("-", 1)[0] if normalized else ""


def detect_digest_locale(digest: dict[str, Any], override: str = "") -> tuple[str, str]:
    explicit = normalize_language(override)
    if explicit:
        return explicit, "override"

    meta = digest.get("meta") if isinstance(digest.get("meta"), dict) else {}
    for value in (
        digest.get("locale"),
        digest.get("language"),
        meta.get("locale"),
        meta.get("language"),
    ):
        normalized = normalize_language(value)
        if normalized:
            return normalized, "artifact"

    return LEGACY_DEFAULT_LOCALE, "legacy_default"


def extract_story_sources(digest: dict[str, Any]) -> list[dict[str, Any]]:
    stories = digest.get("stories")
    if not isinstance(stories, list):
        return []
    out: list[dict[str, Any]] = []
    for index, story in enumerate(stories):
        if not isinstance(story, dict):
            continue
        video_ids = _ordered_ids(story.get("video_ids"))
        if not video_ids:
            continue
        out.append(
            {
                "story_index": index,
                "story_id": _clean(story.get("id")) or f"daily-story-{index + 1}",
                "title": _clean(story.get("title") or story.get("short_title")),
                "source_video_ids": video_ids,
            }
        )
    return out


def normalize_clip(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    video_id = _clean(row.get("id") or row.get("video_id"))
    if len(video_id) != 11:
        return None

    channel = row.get("channel") if isinstance(row.get("channel"), dict) else {}
    duration_raw = row.get("duration") or 0
    duration = int(duration_raw) if str(duration_raw).isdigit() else 0

    return {
        "video_id": video_id,
        "title": _clean(row.get("title")),
        "lang": normalize_language(row.get("lang")),
        "channel_id": _clean(channel.get("id") or row.get("channel_id")),
        "channel_name": _clean(channel.get("name") or channel.get("english_name")),
        "available_at": _clean(row.get("available_at") or row.get("published_at")),
        "duration": duration,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
    }


def source_from_holodex_payload(payload: Any, source_video_id: str) -> dict[str, Any]:
    record: Any = None
    if isinstance(payload, list):
        record = next(
            (
                item
                for item in payload
                if isinstance(item, dict) and _clean(item.get("id")) == source_video_id
            ),
            None,
        )
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        record = next(
            (
                item
                for item in payload["items"]
                if isinstance(item, dict) and _clean(item.get("id")) == source_video_id
            ),
            None,
        )
    elif isinstance(payload, dict) and _clean(payload.get("id")) == source_video_id:
        record = payload

    if not isinstance(record, dict):
        return {"source_language": "", "clips": []}

    raw_clips = record.get("clips")
    if not isinstance(raw_clips, list):
        raw_clips = []

    clips: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_clips:
        clip = normalize_clip(item)
        if clip and clip["video_id"] not in seen:
            seen.add(clip["video_id"])
            clips.append(clip)

    return {
        "source_language": normalize_language(record.get("lang")),
        "clips": clips,
    }


def clips_from_holodex_payload(payload: Any, source_video_id: str) -> list[dict[str, Any]]:
    return source_from_holodex_payload(payload, source_video_id)["clips"]


def holodex_lookup(source_video_id: str, *, api_key: str, timeout: float = 15.0) -> dict[str, Any]:
    if not api_key:
        raise ResolverError("HOLODEX_API_KEY is required for live lookup")

    query = urlencode(
        {
            "id": source_video_id,
            "type": "stream",
            "include": "clips,sources",
            "limit": 1,
        }
    )
    request = Request(
        f"{API_BASE}?{query}",
        headers={
            "X-APIKEY": api_key,
            "Accept": "application/json",
            "User-Agent": "Holodocchi-DailyDigest-Clips/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ResolverError(f"Holodex lookup failed for {source_video_id}: {exc}") from exc

    return source_from_holodex_payload(payload, source_video_id)


def _lookup_result(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(value, dict):
        source_language = normalize_language(value.get("source_language"))
        raw_clips = value.get("clips")
        return source_language, raw_clips if isinstance(raw_clips, list) else []
    if isinstance(value, list):
        return "", value
    return "", []


def _language_tier(clip_language: str, *, digest_locale: str, source_languages: list[str]) -> int:
    clip_family = language_family(clip_language)
    if not clip_family:
        return 4
    if clip_family == language_family(digest_locale):
        return 1
    source_families = {language_family(item) for item in source_languages if language_family(item)}
    if clip_family in source_families:
        return 2
    return 3


def build_sidecar(
    digest: dict[str, Any],
    *,
    lookup: Callable[[str], Any],
    generated_at: str,
    digest_locale: str = "",
) -> dict[str, Any]:
    locale, locale_source = detect_digest_locale(digest, digest_locale)
    stories = extract_story_sources(digest)

    source_video_ids: list[str] = []
    seen_sources: set[str] = set()
    for story in stories:
        for video_id in story["source_video_ids"]:
            if video_id not in seen_sources:
                seen_sources.add(video_id)
                source_video_ids.append(video_id)

    sources: dict[str, dict[str, Any]] = {}
    for video_id in source_video_ids:
        try:
            source_language, clips = _lookup_result(lookup(video_id))
            sources[video_id] = {
                "status": "ok",
                "source_language": source_language,
                "clips": clips,
            }
        except Exception as exc:
            sources[video_id] = {
                "status": "error",
                "error": str(exc),
                "source_language": "",
                "clips": [],
            }

    story_rows: list[dict[str, Any]] = []
    for story in stories:
        source_languages: list[str] = []
        for source_video_id in story["source_video_ids"]:
            lang = normalize_language(sources.get(source_video_id, {}).get("source_language"))
            if lang and lang not in source_languages:
                source_languages.append(lang)

        clips_by_id: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for source_video_id in story["source_video_ids"]:
            for clip in sources.get(source_video_id, {}).get("clips", []):
                clip_id = _clean(clip.get("video_id"))
                if not clip_id:
                    continue
                if clip_id not in clips_by_id:
                    clips_by_id[clip_id] = {**clip, "source_video_ids": []}
                    order.append(clip_id)
                if source_video_id not in clips_by_id[clip_id]["source_video_ids"]:
                    clips_by_id[clip_id]["source_video_ids"].append(source_video_id)

        clips: list[dict[str, Any]] = []
        for provider_order, clip_id in enumerate(order):
            clip = clips_by_id[clip_id]
            clip_source_languages: list[str] = []
            for source_video_id in clip["source_video_ids"]:
                lang = normalize_language(sources.get(source_video_id, {}).get("source_language"))
                if lang and lang not in clip_source_languages:
                    clip_source_languages.append(lang)
            tier = _language_tier(
                normalize_language(clip.get("lang")),
                digest_locale=locale,
                source_languages=clip_source_languages or source_languages,
            )
            clips.append(
                {
                    **clip,
                    "source_languages": clip_source_languages,
                    "language_tier": tier,
                    "_provider_order": provider_order,
                }
            )

        clips.sort(key=lambda row: (row["language_tier"], row["_provider_order"]))
        for clip in clips:
            clip.pop("_provider_order", None)

        story_rows.append(
            {
                **story,
                "digest_locale": locale,
                "source_languages": source_languages,
                "clips": clips,
            }
        )

    status = "ok"
    if any(row["status"] == "error" for row in sources.values()):
        status = "partial"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "target_day": _clean(digest.get("target_day")),
        "generated_at": generated_at,
        "provider": PROVIDER,
        "status": status,
        "digest_sha256": sha256_bytes(canonical_json_bytes(digest)),
        "digest_locale": locale,
        "digest_locale_source": locale_source,
        "language_priority": [
            "digest_locale",
            "source_stream_language",
            "other_known_language",
            "unknown_language",
        ],
        "source_video_ids": source_video_ids,
        "sources": sources,
        "stories": story_rows,
    }


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a refreshable Holodex related-clips sidecar for one accepted Daily Digest."
    )
    parser.add_argument("digest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--digest-locale", default="", help="override Digest locale, e.g. zh-TW, en, ja")
    parser.add_argument("--api-key-env", default="HOLODEX_API_KEY")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when any source lookup fails",
    )
    args = parser.parse_args(argv)

    try:
        digest = json.loads(args.digest.read_text(encoding="utf-8"))
        if not isinstance(digest, dict):
            raise ResolverError("digest root must be an object")
        api_key = os.environ.get(args.api_key_env, "").strip()
        generated_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        sidecar = build_sidecar(
            digest,
            lookup=lambda video_id: holodex_lookup(
                video_id,
                api_key=api_key,
                timeout=args.timeout,
            ),
            generated_at=generated_at,
            digest_locale=args.digest_locale,
        )
        atomic_write(args.output, canonical_json_bytes(sidecar))
    except (OSError, json.JSONDecodeError, ResolverError) as exc:
        print(f"ERROR={exc}", file=os.sys.stderr)
        return 1

    print(f"STATUS={sidecar['status'].upper()}")
    print(f"TARGET_DAY={sidecar['target_day']}")
    print(f"DIGEST_LOCALE={sidecar['digest_locale']}")
    print(f"DIGEST_LOCALE_SOURCE={sidecar['digest_locale_source']}")
    print(f"SOURCE_VIDEOS={len(sidecar['source_video_ids'])}")
    print(f"CLIPS={sum(len(item['clips']) for item in sidecar['stories'])}")
    print(f"OUTPUT={args.output.resolve()}")

    if args.strict and sidecar["status"] != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
