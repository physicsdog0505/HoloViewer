"""Direct, unauthenticated YouTube watch-page public caption acquisition."""
from __future__ import annotations

from collections.abc import Callable
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from transcript_pipeline import TranscriptProviderError, TranscriptSegment
from youtube_transcript_provider import PublicCaptionResult


_PLAYER_MARKERS = (
    re.compile(r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*"),
    re.compile(r'window\["ytInitialPlayerResponse"\]\s*=\s*'),
)


def _public_get(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Hololive-PTT-Viewer/1.0)",
            "Accept-Language": "ja,en;q=0.5",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise TranscriptProviderError(f"public YouTube HTTP {exc.code}") from exc
    except URLError as exc:
        raise TranscriptProviderError("public YouTube request failed") from exc
    except OSError as exc:
        raise TranscriptProviderError("public YouTube response could not be read") from exc


def _balanced_json(text: str, start: int) -> str:
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "{":
        raise TranscriptProviderError("watch page player response is not a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise TranscriptProviderError("watch page player response JSON is incomplete")


def extract_player_response(watch_html: str) -> dict:
    for marker in _PLAYER_MARKERS:
        match = marker.search(watch_html)
        if match:
            try:
                payload = json.loads(_balanced_json(watch_html, match.end()))
            except json.JSONDecodeError as exc:
                raise TranscriptProviderError("watch page player response is invalid JSON") from exc
            if isinstance(payload, dict):
                return payload
    raise TranscriptProviderError("watch page exposes no public player response")


def _caption_tracks(player_response: dict) -> tuple[dict, ...]:
    try:
        tracks = player_response["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    except (KeyError, TypeError):
        raise TranscriptProviderError("player response contains no public caption tracks")
    if not isinstance(tracks, list):
        raise TranscriptProviderError("player response caption tracks are malformed")
    return tuple(track for track in tracks if isinstance(track, dict))


def _track_rank(track: dict) -> tuple[int, int, str]:
    """Prefer human-created tracks, then Japanese when available; never exclude languages."""
    language = str(track.get("languageCode") or "").lower()
    automatic = 1 if track.get("kind") == "asr" else 0
    japanese_preference = 0 if language == "ja" or language.startswith("ja-") else 1
    return automatic, japanese_preference, str(track.get("vssId") or language)


def select_caption_track(player_response: dict) -> dict:
    """Select a usable public caption track without restricting its language."""
    tracks = _caption_tracks(player_response)
    if not tracks:
        raise TranscriptProviderError("player response contains no usable public caption tracks")
    selected = min(tracks, key=_track_rank)
    if not isinstance(selected.get("baseUrl"), str) or not selected["baseUrl"].strip():
        raise TranscriptProviderError("selected public caption track has no URL")
    return selected


def select_japanese_track(player_response: dict) -> dict:
    """Backward-compatible alias; selection is now language-agnostic."""
    return select_caption_track(player_response)


def _json3_url(base_url: str) -> str:
    # Caption URLs may carry signatures over the original query representation.
    # Preserve it byte-for-byte rather than parsing/re-encoding all parameters.
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}fmt=json3"


def validate_public_caption_url(url: str) -> str:
    """Allow anonymous timed-text requests only to HTTPS YouTube hosts."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except (TypeError, ValueError) as exc:
        raise TranscriptProviderError("public caption URL is malformed") from exc
    if parsed.scheme.lower() != "https":
        raise TranscriptProviderError("public caption URL must use HTTPS")
    if not hostname or parsed.username is not None or parsed.password is not None:
        raise TranscriptProviderError("public caption URL is malformed")
    hostname = hostname.rstrip(".").lower()
    if hostname != "youtube.com" and not hostname.endswith(".youtube.com"):
        raise TranscriptProviderError("public caption URL host is not YouTube")
    return url


def parse_json3(text: str) -> tuple[TranscriptSegment, ...]:
    if not text.strip():
        raise TranscriptProviderError("public caption timed-text response is empty")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TranscriptProviderError("public caption response is not valid JSON3") from exc
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise TranscriptProviderError("public caption JSON3 contains no events")
    segments = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        source_text = "".join(
            str(segment.get("utf8") or "")
            for segment in event["segs"] if isinstance(segment, dict)
        ).strip()
        if not source_text:
            continue
        try:
            start_ms = int(event["tStartMs"])
            duration_ms = int(event.get("dDurationMs") or 0)
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriptProviderError("public caption JSON3 timing is malformed") from exc
        segments.append(TranscriptSegment(start_ms, start_ms + max(1, duration_ms), source_text))
    if not segments:
        raise TranscriptProviderError("public caption JSON3 contains no usable cues")
    return tuple(segments)


class DirectYouTubeCaptionProvider:
    """Read public caption metadata and timed text directly from a watch page."""

    name = "youtube-public-page-captions"

    def __init__(self, *, fetch_text: Callable[[str], str] = _public_get) -> None:
        self._fetch_text = fetch_text

    def acquire(self, source: str) -> PublicCaptionResult:
        if not source.strip():
            raise ValueError("source must not be empty")
        player_response = extract_player_response(self._fetch_text(source))
        track = select_caption_track(player_response)
        caption_url = validate_public_caption_url(track["baseUrl"])
        raw_text = self._fetch_text(_json3_url(caption_url))
        language = str(track.get("languageCode") or "unknown")
        track_id = str(track.get("vssId") or language)
        return PublicCaptionResult(
            raw_text=raw_text,
            segments=parse_json3(raw_text),
            language=language,
            track_id=track_id,
            provider=self.name,
        )
