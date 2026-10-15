"""Conservative offline Japanese sentence grouping from timestamped Corpus cues.

This is a candidate grouping algorithm, NOT a claim of correct sentence
boundaries for ASR fragments. Unclosed endings are reported for human review.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from translation_quality_b_pipeline import JapaneseSentence

@dataclass(frozen=True)
class SourceCue:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self):
        if not self.segment_id or self.start_ms < 0 or self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("invalid source cue")

@dataclass(frozen=True)
class Reconstruction:
    sentences: tuple[JapaneseSentence, ...]
    uncertain_sentence_indices: tuple[int, ...]

def reconstruct_sentences(cues: Sequence[SourceCue], *, max_gap_ms: int = 1600,
                          max_sentence_ms: int = 25000) -> Reconstruction:
    if max_gap_ms < 0 or max_sentence_ms <= 0:
        raise ValueError("invalid grouping limits")
    if not cues:
        raise ValueError("source cues required")
    sentences = []
    uncertain = []
    current = []
    def flush(is_uncertain: bool):
        if not current:
            return
        text = "".join(c.text.strip() for c in current)
        sentences.append(JapaneseSentence(current[0].start_ms, current[-1].end_ms,
                                          text, tuple(c.segment_id for c in current)))
        if is_uncertain:
            uncertain.append(len(sentences)-1)
        current.clear()
    seen = set()
    for cue in cues:
        if cue.segment_id in seen: raise ValueError("duplicate source cue ID")
        seen.add(cue.segment_id)
        if current:
            if cue.start_ms < current[-1].end_ms: raise ValueError("source cues overlap")
            if cue.start_ms-current[-1].end_ms > max_gap_ms or cue.end_ms-current[0].start_ms > max_sentence_ms:
                flush(True)
        current.append(cue)
        if cue.text.rstrip().endswith(("。","！","？","!","?")):
            flush(False)
    flush(True)
    return Reconstruction(tuple(sentences),tuple(uncertain))

def require_reviewed_boundaries(result: Reconstruction, reviewed_indices: Sequence[int]=()):
    if set(result.uncertain_sentence_indices)-set(reviewed_indices):
        raise ValueError("ambiguous Japanese sentence boundaries require review")
    return result.sentences
