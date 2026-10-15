"""Offline Chinese subtitle retiming prototype for Translation Quality Lab B.

Input is a *complete translated Japanese sentence* and its source interval.
The translator, not this formatter, owns semantic translation and spoiler-safe
meaning. This module never calls a model or rewrites source timestamps.
"""
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class ChineseCue:
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self):
        if self.start_ms < 0 or self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("Invalid Chinese cue")


def retime_sentence(
    text: str, start_ms: int, end_ms: int, *,
    max_chars: int = 18, min_duration_ms: int = 900,
) -> tuple[ChineseCue, ...]:
    """Deterministic cue distribution weighted by Chinese character count.

    When the source interval is too short for multiple minimum-duration cues,
    preserve the complete text in one bounded cue rather than aborting B.
    Never spill beyond the original speech range or reveal content early.
    """
    if not text or not text.strip() or start_ms < 0 or end_ms <= start_ms:
        raise ValueError("Invalid source sentence")
    if max_chars < 1 or min_duration_ms < 1:
        raise ValueError("Invalid timing policy")
    clean = text.strip()
    if len(clean) <= max_chars:
        return (ChineseCue(start_ms, end_ms, clean),)
    # Prefer natural punctuation boundaries; fall back to conservative chunks.
    pieces = []
    current = ""
    for token in clean:
        current += token
        if len(current) >= max_chars or (token in "，。！？；、" and len(current) >= max_chars // 2):
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    if len(pieces) * min_duration_ms > end_ms - start_ms:
        # Preserve the full translation inside the original speech interval.
        # A single overlong cue is preferable to aborting the entire B job;
        # never spill beyond the source window or drop translated text.
        return (ChineseCue(start_ms, end_ms, clean),)
    total_chars = sum(len(piece) for piece in pieces)
    cursor = start_ms
    output = []
    for index, piece in enumerate(pieces):
        remaining = len(pieces) - index
        if remaining == 1:
            finish = end_ms
        else:
            remaining_duration = end_ms - cursor
            weighted = round((end_ms - start_ms) * len(piece) / total_chars)
            finish = cursor + max(min_duration_ms, min(
                weighted, remaining_duration - (remaining - 1) * min_duration_ms))
        output.append(ChineseCue(cursor, finish, piece))
        cursor = finish
    return tuple(output)


def validate_track(cues: tuple[ChineseCue, ...]) -> None:
    for previous, next_cue in zip(cues, cues[1:]):
        if previous.end_ms > next_cue.start_ms:
            raise ValueError("Chinese subtitles overlap")
