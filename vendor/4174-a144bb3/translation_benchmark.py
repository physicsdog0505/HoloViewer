"""Provider-neutral translation benchmark seam and evaluation metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time
from typing import Any, Sequence

from transcript_pipeline import TranscriptSegment
from translation_pipeline import TranslationProvider, translate_segments

_JP_KANA_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FB\u30FD-\u30FF]")

# Common Simplified Chinese characters for leakage checking in zh-TW benchmarks
_SIMPLIFIED_CHARS_RE = re.compile(r"[这国书门发体关个为时后开进场这说儿还动现来样]")

DEFAULT_GLOSSARY: dict[str, Sequence[str]] = {
    "ぺこら": ("佩克拉", "Pekora"),
    "みこ": ("咪巫", "櫻巫女", "Miko"),
    "同時視聴": ("同時視聽", "Watchalong"),
    "スパチャ": ("Super Chat", "SC", "抖內", "贊助"),
    "おつぺこ": ("辛苦啦，peko", "辛苦了，peko", "otsupeko"),
    "助かる": ("真有幫助", "救命", "感恩"),
}


class GeminiAppImportProvider:
    """TranslationProvider adapter for manually translated text/JSON from Gemini App."""

    def __init__(self, import_source: str | Path | dict | list, name: str = "gemini-app-manual"):
        self.name = name
        self._raw_data = import_source

    def _load_data(self) -> list[dict]:
        if isinstance(self._raw_data, (dict, list)):
            data = self._raw_data
        elif isinstance(self._raw_data, Path) or (isinstance(self._raw_data, str) and Path(self._raw_data).exists()):
            content = Path(self._raw_data).read_text(encoding="utf-8")
            data = json.loads(content)
        elif isinstance(self._raw_data, str):
            data = json.loads(self._raw_data)
        else:
            raise ValueError(f"unsupported import_source type: {type(self._raw_data)}")

        if isinstance(data, dict):
            data = data.get("segments") or data.get("translations") or data.get("items") or []

        if not isinstance(data, list):
            raise ValueError("Gemini App import data must contain a list of items or segments")
        return data

    def translate(self, texts: Sequence[str], *, target_language: str = "zh-TW") -> Sequence[str]:
        if not texts:
            return ()
        raw_list = self._load_data()
        results: dict[int, str] = {}

        for index, item in enumerate(raw_list):
            if isinstance(item, str):
                results[index] = item.strip()
            elif isinstance(item, dict):
                item_id = item.get("id")
                if item_id is None:
                    item_id = index
                elif isinstance(item_id, str) and item_id.isdigit():
                    item_id = int(item_id)

                trans = item.get("translation") or item.get("translated_text") or item.get("text") or ""
                if isinstance(item_id, int) and isinstance(trans, str):
                    results[item_id] = trans.strip()

        outputs: list[str] = []
        for index in range(len(texts)):
            if index in results and results[index]:
                outputs.append(results[index])
            else:
                outputs.append("")  # preserve position, empty recorded
        return tuple(outputs)


@dataclass(frozen=True, slots=True)
class TranslationBenchmarkReport:
    provider: str
    target_language: str
    latency_ms: float
    total_segments: int
    untranslated_jp_leakage: int
    untranslated_jp_leakage_rate: float
    empty_translation_count: int
    empty_translation_rate: float
    segment_count_preservation: bool
    order_preservation: bool
    terminology_consistency_score: float
    zh_tw_readability_score: float
    usage_metadata: dict[str, Any] = field(default_factory=dict)
    segment_details: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "target_language": self.target_language,
            "latency_ms": self.latency_ms,
            "summary": {
                "total_segments": self.total_segments,
                "untranslated_jp_leakage": self.untranslated_jp_leakage,
                "untranslated_jp_leakage_rate": round(self.untranslated_jp_leakage_rate, 4),
                "empty_translation_count": self.empty_translation_count,
                "empty_translation_rate": round(self.empty_translation_rate, 4),
                "segment_count_preservation": self.segment_count_preservation,
                "order_preservation": self.order_preservation,
                "terminology_consistency_score": round(self.terminology_consistency_score, 4),
                "zh_tw_readability_score": round(self.zh_tw_readability_score, 4),
            },
            "usage_metadata": self.usage_metadata,
            "segments": list(self.segment_details),
        }


def evaluate_translation_quality(
    source_segments: Sequence[TranscriptSegment],
    translated_segments: Sequence[TranscriptSegment],
    *,
    provider_name: str = "unknown",
    target_language: str = "zh-TW",
    latency_ms: float = 0.0,
    usage_metadata: dict[str, Any] | None = None,
    glossary: dict[str, Sequence[str]] | None = None,
) -> TranslationBenchmarkReport:
    """Evaluate quality metrics for a translated segment sequence."""
    total = len(source_segments)
    if total == 0:
        return TranslationBenchmarkReport(
            provider=provider_name,
            target_language=target_language,
            latency_ms=latency_ms,
            total_segments=0,
            untranslated_jp_leakage=0,
            untranslated_jp_leakage_rate=0.0,
            empty_translation_count=0,
            empty_translation_rate=0.0,
            segment_count_preservation=True,
            order_preservation=True,
            terminology_consistency_score=1.0,
            zh_tw_readability_score=1.0,
            usage_metadata=usage_metadata or {},
        )

    active_glossary = glossary or DEFAULT_GLOSSARY
    count_preserved = len(translated_segments) == total
    order_preserved = True

    leakage_count = 0
    empty_count = 0
    term_matches = 0
    term_total = 0
    readability_scores: list[float] = []
    details: list[dict[str, Any]] = []

    for index, src in enumerate(source_segments):
        if index >= len(translated_segments):
            order_preserved = False
            break

        trans = translated_segments[index]
        if trans.start_ms != src.start_ms or trans.end_ms != src.end_ms:
            order_preserved = False

        translated_text = (trans.translated_text or "").strip()

        # Check empty translation
        is_empty = not translated_text
        if is_empty:
            empty_count += 1

        # Check JP Kana leakage
        has_leakage = False
        if _JP_KANA_RE.search(source_text := src.source_text):
            if translated_text and _JP_KANA_RE.search(translated_text):
                has_leakage = True
                leakage_count += 1

        # Check glossary terminology consistency
        for jp_term, expected_zh_list in active_glossary.items():
            if jp_term in source_text:
                term_total += 1
                if any(exp in translated_text for exp in expected_zh_list):
                    term_matches += 1

        # Check zh-TW readability Heuristic
        readability = 1.0
        if is_empty:
            readability = 0.0
        else:
            # Penalty for simplified chars
            simp_matches = len(_SIMPLIFIED_CHARS_RE.findall(translated_text))
            if simp_matches > 0:
                readability -= min(0.5, simp_matches * 0.15)

            # Length ratio check vs source
            ratio = len(translated_text) / max(1, len(source_text))
            if ratio < 0.2 or ratio > 2.5:
                readability -= 0.2
        readability_scores.append(max(0.0, readability))

        details.append({
            "index": index,
            "start_ms": src.start_ms,
            "end_ms": src.end_ms,
            "source_text": src.source_text,
            "translated_text": translated_text,
            "has_jp_leakage": has_leakage,
            "is_empty": is_empty,
        })

    leakage_rate = leakage_count / total
    empty_rate = empty_count / total
    term_score = term_matches / term_total if term_total > 0 else 1.0
    avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 1.0

    return TranslationBenchmarkReport(
        provider=provider_name,
        target_language=target_language,
        latency_ms=latency_ms,
        total_segments=total,
        untranslated_jp_leakage=leakage_count,
        untranslated_jp_leakage_rate=leakage_rate,
        empty_translation_count=empty_count,
        empty_translation_rate=empty_rate,
        segment_count_preservation=count_preserved,
        order_preservation=order_preserved,
        terminology_consistency_score=term_score,
        zh_tw_readability_score=avg_readability,
        usage_metadata=usage_metadata or {},
        segment_details=tuple(details),
    )


def run_translation_benchmark(
    segments: Sequence[TranscriptSegment],
    provider: TranslationProvider,
    *,
    target_language: str = "zh-TW",
    max_segments: int = 20,
    max_chars: int = 2000,
    glossary: dict[str, Sequence[str]] | None = None,
) -> TranslationBenchmarkReport:
    """Run a provider on transcript segments and produce a benchmark report."""
    start_time = time.perf_counter()
    res = translate_segments(
        segments,
        provider,
        target_language=target_language,
        max_segments=max_segments,
        max_chars=max_chars,
    )
    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    provider_name = getattr(provider, "name", provider.__class__.__name__)

    usage_meta = getattr(provider, "last_usage", None) or {}
    return evaluate_translation_quality(
        segments,
        res.segments,
        provider_name=provider_name,
        target_language=target_language,
        latency_ms=elapsed_ms,
        usage_metadata=usage_meta,
        glossary=glossary,
    )
