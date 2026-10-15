"""Evidence-driven, offline B semantic segmentation audit.

Do not confuse punctuation heuristics with verified Japanese sentences.
A/B quality claims are blocked until all unresolved boundaries are reviewed.
"""
from __future__ import annotations
from dataclasses import dataclass
from translation_sentence_reconstruction import SourceCue,reconstruct_sentences

@dataclass(frozen=True)
class BoundaryFinding:
    sentence_index: int
    start_ms: int
    end_ms: int
    source_ids: tuple[str,...]
    source_text: str
    uncertain: bool
    reason: str

def inspect_boundaries(ja, *, max_gap_ms=1600, max_sentence_ms=25000):
    from translation_quality_b_long_job import nonoverlap_source
    cues=nonoverlap_source(ja)
    source=tuple(SourceCue(str(i),c["start_ms"],c["end_ms"],c["text"]) for i,c in enumerate(cues))
    result=reconstruct_sentences(source,max_gap_ms=max_gap_ms,max_sentence_ms=max_sentence_ms)
    findings=[]
    for idx,s in enumerate(result.sentences):
        uncertain=idx in result.uncertain_sentence_indices
        if uncertain:
            reason="No reliable closing punctuation or hard timing/gap boundary: manual review required"
        else:
            reason="Punctuation-derived candidate, not semantic quality certification"
        findings.append(BoundaryFinding(idx,s.start_ms,s.end_ms,s.source_ids,s.source_text,uncertain,reason))
    flattened=[source_id for s in result.sentences for source_id in s.source_ids]
    if flattened!=[cue.segment_id for cue in source]:
        raise ValueError("Japanese source cue loss, reordering or duplication")
    return tuple(findings)

def audit_translated_cues(ja, translated, source_spans):
    """Never return quality=better; only check measurable coverage and timings."""
    from translation_quality_b_long_job import nonoverlap_source
    cues=nonoverlap_source(ja)
    from translation_quality_b_long_job import source_cues
    output=source_cues(translated)
    if any(left['end_ms'] > right['start_ms'] for left,right in zip(output,output[1:])):
        raise ValueError('B output overlaps')
    if len(output)!=len(source_spans):
        raise ValueError("B missing subtitle source provenance")
    allowed={str(i) for i in range(len(cues))}
    covered=set()
    for cue,span in zip(output,source_spans):
        ids=list(span)
        if not ids or len(set(ids))!=len(ids) or any(id not in allowed for id in ids):
            raise ValueError("Unknown or duplicate B source IDs")
        covered.update(ids)
        lo=min(cues[int(id)]["start_ms"] for id in ids)
        hi=max(cues[int(id)]["end_ms"] for id in ids)
        if cue["start_ms"]<lo or cue["end_ms"]>hi:
            raise ValueError("B cue leaks outside the original Japanese utterance window")
    missing=sorted(allowed-covered,key=int)
    if missing:raise ValueError("B output omits Japanese source content")
    return {"source_count":len(cues),"translated_count":len(output),
            "coverage":1.0,"semantic_quality_verified":False}
