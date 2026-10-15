"""Public YouTube VOD transcript provider backed by the yt-dlp CLI.

This adapter intentionally handles public archived VOD captions only. It does not
read browser cookies, Keychain data, API keys, or production databases. The
provider downloads a temporary WebVTT subtitle file and normalizes it into the
provider-agnostic ``TranscriptSegment`` model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
import re
import subprocess
import tempfile

from transcript_pipeline import TranscriptProviderError, TranscriptSegment


_TIMESTAMP = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})[.,](?P<fraction>\d{1,4})$"
)
_INLINE_TAG = re.compile(r"<[^>]+>")
_METADATA_BLOCKS = {"NOTE", "STYLE", "REGION"}


@dataclass(frozen=True, slots=True)
class PublicCaptionResult:
    raw_text: str
    segments: tuple[TranscriptSegment, ...]
    language: str
    track_id: str
    provider: str
    provenance: dict[str, object] = field(default_factory=dict)


def _timestamp_ms(value: str) -> int:
    match = _TIMESTAMP.match(value.strip())
    if not match:
        raise ValueError(f"invalid WebVTT timestamp: {value!r}")
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    fraction = match.group("fraction")
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"invalid WebVTT timestamp: {value!r}")
    millis = int((fraction + "000")[:3])
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _clean_cue_text(lines: Sequence[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = _INLINE_TAG.sub("", text)
    return unescape(text).strip()


def _is_metadata_block(line: str) -> bool:
    token = line.split(maxsplit=1)[0].rstrip(":") if line else ""
    return token in _METADATA_BLOCKS


def parse_webvtt(text: str) -> tuple[TranscriptSegment, ...]:
    """Parse the subset of WebVTT needed for YouTube caption cues.

    Cue overlap is preserved intentionally. YouTube rolling captions may overlap,
    but deleting repeated-looking text without provider evidence risks removing
    legitimate repeated speech. Later QA/provider-specific logic can classify it.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line or line == "WEBVTT":
            index += 1
            continue
        if _is_metadata_block(line):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        if "-->" not in line:
            index += 1
            if index >= len(lines):
                break
            line = lines[index].strip()

        if "-->" not in line:
            index += 1
            continue

        start_raw, end_and_settings = (part.strip() for part in line.split("-->", 1))
        end_raw = end_and_settings.split()[0]
        try:
            start_ms = _timestamp_ms(start_raw)
            end_ms = _timestamp_ms(end_raw)
        except ValueError as exc:
            raise TranscriptProviderError(str(exc)) from exc
        if end_ms <= start_ms:
            raise TranscriptProviderError(
                f"invalid WebVTT cue range: {start_raw} --> {end_raw}"
            )

        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index])
            index += 1
        source_text = _clean_cue_text(cue_lines)
        if source_text:
            segments.append(TranscriptSegment(start_ms, end_ms, source_text))

    return tuple(segments)


def _subtitle_rank(path: Path) -> tuple[int, str]:
    """Prefer a human-provided track when available, independent of language."""
    name = path.name.lower()
    if name.endswith("-orig.vtt"):
        return (1, name)
    return (0, name)


class YtDlpSubtitleProvider:
    """Fetch public-VOD captions in any available language with yt-dlp."""

    name = "yt-dlp-captions"

    def __init__(
        self,
        *,
        executable: str = "yt-dlp",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.executable = executable
        self._runner = runner

    def acquire(self, source: str) -> PublicCaptionResult:
        """Acquire one available public caption track without authentication."""
        if not source.strip():
            raise ValueError("source must not be empty")

        with tempfile.TemporaryDirectory(prefix="ptt-vod-subs-") as temp_dir:
            temp_path = Path(temp_dir)
            output_template = str(temp_path / "%(id)s.%(language)s.%(ext)s")
            command = [
                self.executable,
                "--ignore-config",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "all",
                "--sub-format",
                "vtt",
                "--skip-download",
                "--no-playlist",
                "--output",
                output_template,
                source,
            ]
            try:
                result = self._runner(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=90,
                )
            except FileNotFoundError as exc:
                raise TranscriptProviderError(
                    f"yt-dlp executable not found: {self.executable}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise TranscriptProviderError("yt-dlp subtitle request timed out") from exc
            except OSError as exc:
                raise TranscriptProviderError(
                    f"yt-dlp could not be started: {type(exc).__name__}: {exc}"
                ) from exc

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "yt-dlp failed").strip()
                detail = detail[-1000:]
                raise TranscriptProviderError(
                    f"yt-dlp subtitle acquisition failed ({result.returncode}): {detail}"
                )

            subtitle_files = sorted(temp_path.glob("*.vtt"), key=_subtitle_rank)
            if not subtitle_files:
                raise TranscriptProviderError(
                    "yt-dlp completed but produced no WebVTT subtitle in any language"
                )

            try:
                payload = subtitle_files[0].read_text(encoding="utf-8")
            except OSError as exc:
                raise TranscriptProviderError(
                    f"could not read downloaded subtitle: {type(exc).__name__}: {exc}"
                ) from exc

            segments = parse_webvtt(payload)
            if not segments:
                raise TranscriptProviderError("downloaded subtitle contained no usable cues")
            track_id = subtitle_files[0].name.rsplit(".", 2)[-2]
            language = track_id.removesuffix("-orig")
            return PublicCaptionResult(
                raw_text=payload,
                segments=segments,
                language=language,
                track_id=track_id,
                provider=self.name,
            )

    def transcribe(self, source: str) -> Sequence[TranscriptSegment]:
        """Compatibility adapter for the generic transcript provider contract."""
        return self.acquire(source).segments
