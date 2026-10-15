"""Anonymous mobile InnerTube provider for public YouTube caption tracks."""
from __future__ import annotations

from dataclasses import dataclass
import gzip
from html import unescape
import json
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from direct_youtube_caption_provider import parse_json3, select_caption_track
from frontend_time import youtube_video_id
from transcript_pipeline import TranscriptProviderError, TranscriptSegment
from youtube_transcript_provider import PublicCaptionResult


INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CLIENTS = {
    "ANDROID": {
        "clientName": "ANDROID",
        "clientVersion": "20.10.38",
        "androidSdkVersion": 30,
        "hl": "en",
        "gl": "US",
        "user_agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip",
    },
    "IOS": {
        "clientName": "IOS",
        "clientVersion": "20.10.4",
        "deviceModel": "iPhone16,2",
        "hl": "en",
        "gl": "US",
        "user_agent": "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_0 like Mac OS X)",
    },
}


@dataclass(frozen=True, slots=True)
class HttpTextResponse:
    status: int
    text: str


def _validate_youtube_https(url: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "youtube.com" or host.endswith(".youtube.com")):
        raise TranscriptProviderError("InnerTube returned a non-YouTube caption URL")


def _request_text(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpTextResponse:
    _validate_youtube_https(url)
    request = Request(url, data=body, method=method, headers=dict(headers or {}))
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise TranscriptProviderError("YouTube response exceeds safe size limit")
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except (OSError, EOFError) as exc:
                    raise TranscriptProviderError("YouTube gzip response is malformed") from exc
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise TranscriptProviderError("YouTube response exceeds safe size limit")
            return HttpTextResponse(response.status, raw.decode("utf-8", errors="replace"))
    except HTTPError as exc:
        return HttpTextResponse(exc.code, exc.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace"))
    except (URLError, OSError) as exc:
        raise TranscriptProviderError("anonymous YouTube request failed") from exc


def _format_url(base_url: str, format_name: str) -> str:
    _validate_youtube_https(base_url)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}fmt={format_name}"


def parse_srv1(text: str) -> tuple[TranscriptSegment, ...]:
    if not text.strip():
        raise TranscriptProviderError("public caption SRV1 response is empty")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TranscriptProviderError("public caption SRV1 response is malformed") from exc
    segments = []
    items = root.findall(".//text")
    timing_unit = 1000
    if not items:
        # Android currently returns timedtext format=3 even when fmt=json3 is
        # requested. Its <p> timing attributes are already milliseconds.
        items = root.findall(".//p")
        timing_unit = 1
    for item in items:
        source_text = unescape("".join(item.itertext())).strip()
        if not source_text:
            continue
        try:
            start_value = item.attrib.get("start", item.attrib.get("t"))
            duration_value = item.attrib.get("dur", item.attrib.get("d", "0"))
            if start_value is None:
                raise KeyError("start")
            start_ms = round(float(start_value) * timing_unit)
            duration_ms = round(float(duration_value) * timing_unit)
        except (KeyError, ValueError) as exc:
            raise TranscriptProviderError("public caption SRV1 timing is malformed") from exc
        segments.append(TranscriptSegment(start_ms, start_ms + max(1, duration_ms), source_text))
    if not segments:
        raise TranscriptProviderError("public caption SRV1 contains no usable cues")
    return tuple(segments)


def _parse_caption_response(
    text: str, requested_format: str
) -> tuple[tuple[TranscriptSegment, ...], str]:
    if requested_format == "srv1":
        return parse_srv1(text), "srv1"
    try:
        return parse_json3(text), "json3"
    except TranscriptProviderError:
        if not text.lstrip().startswith("<?xml"):
            raise
        return parse_srv1(text), "timedtext_xml"


class InnerTubeCaptionProvider:
    """Acquire public captions using one anonymous official mobile client identity."""

    def __init__(
        self,
        client: str,
        *,
        request_text: Callable[..., HttpTextResponse] = _request_text,
    ) -> None:
        normalized = client.upper()
        if normalized not in CLIENTS:
            raise ValueError(f"unsupported InnerTube client: {client}")
        self.client = normalized
        self.name = f"youtube-innertube-{normalized.lower()}"
        self._request_text = request_text

    def acquire(self, source: str) -> PublicCaptionResult:
        video_id = youtube_video_id(source)
        if video_id is None:
            raise ValueError("a valid YouTube video URL or id is required")
        profile = CLIENTS[self.client]
        context = {key: value for key, value in profile.items() if key != "user_agent"}
        request_body = json.dumps(
            {"context": {"client": context}, "videoId": video_id},
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request_text(
            INNERTUBE_URL,
            method="POST",
            body=request_body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": str(profile["user_agent"]),
                "Accept-Language": "en",
            },
        )
        if response.status != 200:
            raise TranscriptProviderError(
                f"InnerTube {self.client} player HTTP {response.status}"
            )
        try:
            player = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise TranscriptProviderError(
                f"InnerTube {self.client} player response is malformed"
            ) from exc
        if not isinstance(player, dict):
            raise TranscriptProviderError(
                f"InnerTube {self.client} player response is malformed"
            )
        track = select_caption_track(player)
        base_url = str(track["baseUrl"])
        exp_xpe = "exp=xpe" in base_url
        failures = []
        for format_name in ("json3", "srv1"):
            caption_response = self._request_text(
                _format_url(base_url, format_name),
                headers={"User-Agent": str(profile["user_agent"])},
            )
            if caption_response.status != 200:
                failures.append(
                    f"{format_name}=HTTP {caption_response.status} "
                    f"bytes={len(caption_response.text.encode('utf-8'))}"
                )
                continue
            try:
                segments, actual_format = _parse_caption_response(
                    caption_response.text, format_name
                )
            except TranscriptProviderError as exc:
                failures.append(
                    f"{format_name}={exc} "
                    f"bytes={len(caption_response.text.encode('utf-8'))}"
                )
                continue
            language = str(track.get("languageCode") or "unknown")
            track_id = str(track.get("vssId") or language)
            return PublicCaptionResult(
                raw_text=caption_response.text,
                segments=segments,
                language=language,
                track_id=track_id,
                provider=self.name,
                provenance={
                    "innertube_client": self.client,
                    "client_version": profile["clientVersion"],
                    "caption_format": actual_format,
                    "caption_exp_xpe": exp_xpe,
                    "caption_http_status": caption_response.status,
                    "caption_response_bytes": len(caption_response.text.encode("utf-8")),
                    "track_kind": track.get("kind") or "manual",
                },
            )
        raise TranscriptProviderError(
            f"InnerTube {self.client} caption download failed "
            f"(language={track.get('languageCode') or 'unknown'}, "
            f"kind={track.get('kind') or 'manual'}, "
            f"vssId={track.get('vssId') or 'unknown'}, exp_xpe={exp_xpe}): "
            + "; ".join(failures)
        )
