from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PUBLIC_KIND = "holodocchi.daily_digest"
PUBLIC_SCHEMA_VERSION = 1
GEMINI_V2_SCHEMA = "holodocchi.gemini.daily_digest.v2"
VALID_OVERVIEW_LAYOUTS = {"compact", "rail", "lead"}
VALID_ROLES = {"lead_candidate", "secondary_candidate", "normal"}

SHORT_TITLE_TARGET_MIN = 12
SHORT_TITLE_TARGET_MAX = 32
SHORT_TITLE_HARD_MIN = 8
SHORT_TITLE_HARD_MAX = 42
HIGHLIGHT_SUMMARY_MIN = 45
HIGHLIGHT_SUMMARY_MAX = 110
OVERVIEW_MIN = 260
OVERVIEW_MAX = 520
STORY_EDITORIAL_TARGET_MIN = 320
STORY_EDITORIAL_MAX = 760


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizeResult:
    artifact: dict[str, Any]
    warnings: tuple[str, ...]
    source_sha256: str


def canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def source_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _split_legacy_highlight(value: str) -> tuple[str, str]:
    raw = _clean(value)
    for sep in ("：", ":"):
        if sep in raw:
            title, rest = raw.split(sep, 1)
            return _clean(title), _clean(rest)
    return raw, raw


def _truncate(value: str, maximum: int) -> str:
    raw = _clean(value)
    if len(raw) <= maximum:
        return raw
    candidate = raw[:maximum]
    for token in ("。", "！", "？", "；", "，", "、", " "):
        pos = candidate.rfind(token, maximum // 2)
        if pos >= 0:
            candidate = candidate[: pos + 1]
            break
    candidate = candidate.rstrip()
    if len(candidate) >= maximum:
        candidate = candidate[: maximum - 1].rstrip()
    return candidate + "…"


def _derive_short_title(title: str) -> str:
    raw = _clean(title)
    if len(raw) <= SHORT_TITLE_HARD_MAX:
        return raw
    for sep in ("：", ":", "—", "－", "｜", "|"):
        head = _clean(raw.split(sep, 1)[0])
        if SHORT_TITLE_HARD_MIN <= len(head) <= SHORT_TITLE_HARD_MAX:
            return head
    return _truncate(raw, SHORT_TITLE_HARD_MAX)


def _ordered_video_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        vid = _clean(item)
        if vid and vid not in seen:
            seen.add(vid)
            out.append(vid)
    return out


def _layout_from_hint(hint: Any, highlights: list[dict[str, Any]]) -> tuple[str, str | None]:
    requested = _clean(hint).lower()
    if requested in VALID_OVERVIEW_LAYOUTS:
        return requested, None
    lengths = [len(_clean(item.get("short_title") or item.get("title"))) for item in highlights[:5]]
    first = lengths[0] if lengths else 0
    maximum = max(lengths, default=0)
    average = (sum(lengths) / len(lengths)) if lengths else 0
    long_count = sum(1 for length in lengths if length > 32)
    if first > 34 or maximum > 42:
        fallback = "lead"
    elif long_count >= 2 or average > 29:
        fallback = "rail"
    else:
        fallback = "compact"
    warning = None if not requested else f"invalid overview presentation_hint={requested!r}; resolved={fallback}"
    return fallback, warning


def _normalize_highlight(item: Any, story: dict[str, Any] | None, *, legacy: bool, index: int) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    story = story or {}
    if isinstance(item, str):
        title, summary = _split_legacy_highlight(item)
        short_title = _derive_short_title(title)
        video_ids = _ordered_video_ids(story.get("video_ids"))
        role = _clean((story.get("editorial_signals") or {}).get("recommended_role")) or "normal"
        return {
            "title": title,
            "short_title": short_title,
            "summary": _truncate(summary, HIGHLIGHT_SUMMARY_MAX),
            "video_ids": video_ids,
            "recommended_role": role if role in VALID_ROLES else "normal",
        }, warnings

    if not isinstance(item, dict):
        raise ContractError(f"overview.highlights[{index}] must be string or object")

    title = _clean(item.get("title"))
    short_title = _clean(item.get("short_title")) or _derive_short_title(title)
    summary = _clean(item.get("summary") or item.get("public_summary"))
    video_ids = _ordered_video_ids(item.get("video_ids"))
    if legacy and not video_ids:
        video_ids = _ordered_video_ids(story.get("video_ids"))
    role = _clean(item.get("recommended_role")) or _clean((story.get("editorial_signals") or {}).get("recommended_role")) or "normal"

    if not title:
        raise ContractError(f"overview.highlights[{index}].title is required")
    if len(short_title) > SHORT_TITLE_HARD_MAX:
        warnings.append(f"overview.highlights[{index}].short_title normalized from {len(short_title)} to <= {SHORT_TITLE_HARD_MAX}")
        short_title = _derive_short_title(short_title)
    if len(short_title) < SHORT_TITLE_HARD_MIN and not legacy:
        raise ContractError(f"overview.highlights[{index}].short_title must be at least {SHORT_TITLE_HARD_MIN} chars")
    if not summary:
        raise ContractError(f"overview.highlights[{index}].summary is required")
    if len(summary) > HIGHLIGHT_SUMMARY_MAX:
        warnings.append(f"overview.highlights[{index}].summary normalized from {len(summary)} to <= {HIGHLIGHT_SUMMARY_MAX}")
        summary = _truncate(summary, HIGHLIGHT_SUMMARY_MAX)
    if len(summary) < HIGHLIGHT_SUMMARY_MIN and not legacy:
        raise ContractError(f"overview.highlights[{index}].summary must be at least {HIGHLIGHT_SUMMARY_MIN} chars")
    if not video_ids and not legacy:
        raise ContractError(f"overview.highlights[{index}].video_ids must retain evidence")
    if role not in VALID_ROLES:
        warnings.append(f"overview.highlights[{index}].recommended_role={role!r} normalized to normal")
        role = "normal"

    return {
        "title": title,
        "short_title": short_title,
        "summary": summary,
        "video_ids": video_ids,
        "recommended_role": role,
    }, warnings


def _char_bigrams(value: str) -> set[str]:
    compact = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", _clean(value))
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def _overlap_ratio(a: str, b: str) -> float:
    left = _char_bigrams(a)
    right = _char_bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _story_editorial_summary(story: dict[str, Any], stream_by_id: dict[str, dict[str, Any]]) -> str:
    explicit = _clean(story.get("editorial_summary"))
    if explicit:
        return _truncate(explicit, STORY_EDITORIAL_MAX) if len(explicit) > STORY_EDITORIAL_MAX else explicit

    base = _clean(story.get("public_summary") or story.get("summary"))
    if len(base) >= STORY_EDITORIAL_TARGET_MIN:
        return _truncate(base, STORY_EDITORIAL_MAX) if len(base) > STORY_EDITORIAL_MAX else base

    parts: list[str] = [base] if base else []
    for video_id in _ordered_video_ids(story.get("video_ids")):
        stream = stream_by_id.get(video_id) or {}
        candidate = _clean(stream.get("summary") or stream.get("public_summary"))
        if not candidate:
            continue

        # Migration fallback: when a richer stream summary substantially overlaps
        # the compact story summary, treat it as an expanded version of the same
        # editorial beat instead of showing both versions side-by-side.
        if parts and _overlap_ratio(parts[0], candidate) >= 0.28 and len(candidate) > len(parts[0]):
            parts[0] = candidate
        elif any(_overlap_ratio(existing, candidate) >= 0.42 for existing in parts):
            continue
        else:
            parts.append(candidate)

        joined = " ".join(parts)
        if len(joined) >= STORY_EDITORIAL_TARGET_MIN:
            break

    editorial = " ".join(part for part in parts if part).strip()
    if len(editorial) > STORY_EDITORIAL_MAX:
        editorial = _truncate(editorial, STORY_EDITORIAL_MAX)
    return editorial


def _normalize_story(
    story: Any,
    *,
    legacy: bool,
    index: int,
    stream_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(story, dict):
        raise ContractError(f"stories[{index}] must be object")
    out = copy.deepcopy(story)
    warnings: list[str] = []
    title = _clean(out.get("title"))
    if not title:
        raise ContractError(f"stories[{index}].title is required")
    out["title"] = title
    if out.get("short_title"):
        out["short_title"] = _derive_short_title(_clean(out["short_title"]))
    elif not legacy:
        out["short_title"] = _derive_short_title(title)

    public_summary = _clean(out.get("public_summary") or out.get("summary"))
    if public_summary:
        out["public_summary"] = public_summary

    out["video_ids"] = _ordered_video_ids(out.get("video_ids"))
    editorial_summary = _story_editorial_summary(out, stream_by_id)
    if editorial_summary:
        out["editorial_summary"] = editorial_summary

    hint = _clean(out.get("presentation_hint")).lower()
    if hint and hint not in VALID_OVERVIEW_LAYOUTS:
        warnings.append(f"stories[{index}].presentation_hint={hint!r} dropped")
        out.pop("presentation_hint", None)
    return out, warnings


def normalize_digest(payload: dict[str, Any]) -> NormalizeResult:
    if not isinstance(payload, dict):
        raise ContractError("source must be an object")

    original = copy.deepcopy(payload)
    warnings: list[str] = []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    source_schema = _clean(
        meta.get("schema_version")
        or payload.get("schema")
        or payload.get("schema_version_name")
        or payload.get("gemini_schema_version")
    )
    is_v2 = source_schema == GEMINI_V2_SCHEMA or _clean(payload.get("SCHEMA_VERSION")) == GEMINI_V2_SCHEMA
    legacy = not is_v2

    out = copy.deepcopy(payload)
    out["schema_version"] = PUBLIC_SCHEMA_VERSION
    out["kind"] = PUBLIC_KIND
    out.pop("schema", None)
    out.pop("schema_version_name", None)
    out.pop("gemini_schema_version", None)
    out.pop("SCHEMA_VERSION", None)

    target_day = _clean(out.get("target_day") or meta.get("target_day"))
    timezone = _clean(out.get("timezone") or meta.get("timezone"))
    if is_v2 and not target_day:
        raise ContractError("meta.target_day/target_day is required")
    if is_v2 and not timezone:
        raise ContractError("meta.timezone/timezone is required")
    if target_day:
        out["target_day"] = target_day
    if timezone:
        out["timezone"] = timezone

    overview = out.get("overview")
    if not isinstance(overview, dict):
        raise ContractError("overview must be an object")
    stories_src = out.get("stories") if isinstance(out.get("stories"), list) else []

    summary = _clean(overview.get("public_summary") or overview.get("summary"))
    if not summary:
        raise ContractError("overview.public_summary/summary is required")
    if len(summary) > OVERVIEW_MAX:
        warnings.append(f"overview.public_summary normalized from {len(summary)} to <= {OVERVIEW_MAX}")
        summary = _truncate(summary, OVERVIEW_MAX)
    if is_v2 and len(summary) < OVERVIEW_MIN:
        raise ContractError(f"overview.public_summary must be at least {OVERVIEW_MIN} chars")

    highlights_src = overview.get("highlights")
    if not isinstance(highlights_src, list):
        raise ContractError("overview.highlights must be an array")
    if is_v2 and not 3 <= len(highlights_src) <= 5:
        raise ContractError("v2 overview.highlights must contain 3-5 items")

    highlights: list[dict[str, Any]] = []
    for index, item in enumerate(highlights_src[:5]):
        story = stories_src[index] if index < len(stories_src) and isinstance(stories_src[index], dict) else None
        normalized, local_warnings = _normalize_highlight(item, story, legacy=legacy, index=index)
        highlights.append(normalized)
        warnings.extend(local_warnings)

    layout, warning = _layout_from_hint(overview.get("presentation_hint") or out.get("overview_layout"), highlights)
    if warning:
        warnings.append(warning)

    new_overview = copy.deepcopy(overview)
    new_overview["public_summary"] = summary
    new_overview["highlights"] = highlights
    if is_v2 and _clean(overview.get("presentation_hint")):
        new_overview["presentation_hint"] = _clean(overview.get("presentation_hint")).lower()
    out["overview"] = new_overview
    out["overview_layout"] = layout

    if stories_src:
        stream_by_id = {
            _clean(row.get("video_id")): row
            for row in (out.get("streams") if isinstance(out.get("streams"), list) else [])
            if isinstance(row, dict) and _clean(row.get("video_id"))
        }
        stories: list[dict[str, Any]] = []
        for index, story in enumerate(stories_src):
            normalized, local_warnings = _normalize_story(
                story,
                legacy=legacy,
                index=index,
                stream_by_id=stream_by_id,
            )
            stories.append(normalized)
            warnings.extend(local_warnings)
        out["stories"] = stories

    if isinstance(out.get("announcements"), list):
        for row in out["announcements"]:
            if isinstance(row, dict) and "video_ids" in row:
                row["video_ids"] = _ordered_video_ids(row.get("video_ids"))
    if isinstance(out.get("categories"), list):
        for row in out["categories"]:
            if isinstance(row, dict):
                row["video_ids"] = _ordered_video_ids(row.get("video_ids"))

    provenance = out.get("producer_v2") if isinstance(out.get("producer_v2"), dict) else {}
    provenance.update({
        "normalizer": "daily_digest_normalizer_v2",
        "source_schema": GEMINI_V2_SCHEMA if is_v2 else "legacy-v1",
        "source_sha256": source_sha256(original),
    })
    out["producer_v2"] = provenance

    return NormalizeResult(artifact=out, warnings=tuple(warnings), source_sha256=source_sha256(original))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize Gemini Daily Digest v1/v2 output into the public artifact contract.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-copy", type=Path, help="Optional durable canonical copy of the unmodified source input.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = normalize_digest(payload)
    _write_json(args.output, result.artifact)
    if args.source_copy:
        _write_json(args.source_copy, payload)
    print(f"SOURCE_SHA256={result.source_sha256}")
    print(f"OVERVIEW_LAYOUT={result.artifact['overview_layout']}")
    print(f"WARNINGS={len(result.warnings)}")
    for warning in result.warnings:
        print(f"WARNING={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
