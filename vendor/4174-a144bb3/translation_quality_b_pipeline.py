"""Experimental B pipeline: source sentence units -> independent zh-TW track.

Offline, no Gemini calls. A future provider adapter is injected explicitly.
No partially finished subtitle track is returned.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence
from translation_chinese_retiming import ChineseCue, retime_sentence, validate_track


@dataclass(frozen=True)
class JapaneseSentence:
    start_ms: int
    end_ms: int
    source_text: str
    source_ids: tuple[str, ...]

    def __post_init__(self):
        if self.start_ms < 0 or self.end_ms <= self.start_ms or not self.source_text.strip() or not self.source_ids:
            raise ValueError("invalid Japanese sentence")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("duplicate source IDs")


@dataclass(frozen=True)
class BResult:
    source_count: int
    chinese_cues: tuple[ChineseCue, ...]
    source_spans: tuple[tuple[str, ...], ...]
    complete: bool


def build_b_track(
    sentences: Sequence[JapaneseSentence],
    translate: Callable[[str, str], str],
    *,
    context: str,
    max_chars: int = 18,
    min_duration_ms: int = 900,
) -> BResult:
    """Translate complete sentence units. Return only after all validate.

    Caller must first reconstruct and review sentence boundaries. Do not infer
    sentence boundaries from fragmented ASR solely based on punctuation.
    """
    if not sentences or not isinstance(context, str):
        raise ValueError("source sentences and context required")
    output: list[ChineseCue] = []
    spans: list[tuple[str, ...]] = []
    observed_ids: set[str] = set()
    for index, sentence in enumerate(sentences):
        if index and sentence.start_ms < sentences[index-1].end_ms:
            raise ValueError("overlapping Japanese sentences")
        if observed_ids.intersection(sentence.source_ids):
            raise ValueError("source ID repeated across sentences")
        observed_ids.update(sentence.source_ids)
        translated = translate(sentence.source_text, context)
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("empty B translation")
        cues = retime_sentence(translated, sentence.start_ms, sentence.end_ms,
                               max_chars=max_chars, min_duration_ms=min_duration_ms)
        output.extend(cues)
        spans.extend([sentence.source_ids] * len(cues))
    validate_track(tuple(output))
    return BResult(len(sentences), tuple(output), tuple(spans), True)
