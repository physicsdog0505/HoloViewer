"""Experimental Gemini translation-quality v2 stages for Issue #198.

This module is intentionally isolated from the accepted production translation route.
It provides:
- initial translation with optional glossary + bounded rolling context;
- structured translation quality review (QE);
- one-pass selective post-editing that preserves unflagged text byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence

from gemini_translation_provider import GeminiTranslationProvider
from translation_pipeline import TranslationProviderError


_ALLOWED_TARGETS = {"zh-tw", "zh_hant", "traditional-chinese"}
_ALLOWED_ISSUES = {
    "meaning_error",
    "omission",
    "addition_or_hallucination",
    "terminology",
    "name_or_nickname",
    "unnatural_zh_tw",
    "jp_leakage",
    "asr_uncertainty",
    "context_reference",
}
_ALLOWED_SEVERITIES = {"none", "minor", "major", "critical"}
_JP_KANA_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FB\u30FD-\u30FF]")

_BRACKETED_CUE_MAP = {
    "[笑い]": "[笑]",
    "[拍手]": "[掌聲]",
    "[音楽]": "[音樂]",
    "[歓声]": "[歡呼]",
    "[ため息]": "[嘆氣]",
}


def normalize_bracketed_cues(text: str) -> str:
    """Normalize copied Japanese non-speech cue labels deterministically."""
    normalized = text
    for source, target in _BRACKETED_CUE_MAP.items():
        normalized = normalized.replace(source, target)
    return normalized


def has_residual_japanese_kana(text: str) -> bool:
    """Return True when zh-TW output still contains Japanese kana."""
    return bool(_JP_KANA_RE.search(text))


def _validate_target(target_language: str) -> None:
    if target_language.lower() not in _ALLOWED_TARGETS:
        raise TranslationProviderError(
            f"Gemini quality v2 currently expects Traditional Chinese, got {target_language!r}"
        )


def _glossary_payload(glossary: Mapping[str, Sequence[str]] | None) -> list[dict[str, Any]]:
    if not glossary:
        return []
    return [
        {"source": source, "accepted_zh_tw": list(values)}
        for source, values in sorted(glossary.items())
    ]


def _decode_json_array(raw_text: str | None, *, stage: str) -> list[dict[str, Any]]:
    if not raw_text:
        raise TranslationProviderError(f"{stage} returned no text")
    try:
        decoded = json.loads(raw_text)
    except Exception as exc:
        raise TranslationProviderError(
            f"{stage} returned invalid JSON: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(decoded, list) or any(not isinstance(item, dict) for item in decoded):
        raise TranslationProviderError(f"{stage} JSON must be an array of objects")
    return decoded


class _GeminiQualityStage:
    def __init__(
        self,
        *,
        model: str = "gemini-3.5-flash-lite",
        client: Any | None = None,
        provider: GeminiTranslationProvider | None = None,
    ) -> None:
        self._provider = provider or GeminiTranslationProvider(model=model, client=client)
        self.model = self._provider.model
        self.request_count = 0
        self.last_usage: dict[str, int] = {}

    def _client(self) -> Any:
        return self._provider._load_client()

    @staticmethod
    def _usage_value(usage: Any, field: str) -> int:
        if usage is None:
            return 0
        if isinstance(usage, Mapping):
            value = usage.get(field, 0)
        else:
            value = getattr(usage, field, 0)
        return int(value or 0)

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        fields = (
            "prompt_token_count",
            "candidates_token_count",
            "thoughts_token_count",
            "cached_content_token_count",
            "tool_use_prompt_token_count",
            "total_token_count",
        )
        for field in fields:
            value = self._usage_value(usage, field)
            if value:
                self.last_usage[field] = self.last_usage.get(field, 0) + value
        self.request_count += 1
        self.last_usage["request_count"] = self.request_count

    def _generate(self, prompt: str, schema: dict[str, Any], *, stage: str) -> list[dict[str, Any]]:
        # Shared by initial, review and post-edit, including repair calls.
        # Guard errors must propagate BEFORE contacting the Gemini API.
        guard = getattr(self._provider, 'generation_guard', None)
        if guard is not None:
            # Convert existing human-readable stage labels to ledger identifiers.
            # Repair belongs to initial translation; unknown stages must fail closed.
            normalized = stage.lower().replace("-", "_")
            if "post_edit" in normalized:
                budget_stage = "post_edit"
            elif "review" in normalized:
                budget_stage = "review"
            elif "translation" in normalized or "repair" in normalized or normalized == "initial":
                budget_stage = "initial"
            else:
                raise ValueError("unrecognized Gemini request stage for budget guard")
            guard(budget_stage, prompt)
        try:
            response = self._client().models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": schema,
                    "temperature": 0,
                },
            )
        except Exception as exc:
            raise TranslationProviderError(
                f"{stage} request failed: {type(exc).__name__}: {exc}"
            ) from exc
        self._record_usage(response)
        return _decode_json_array(getattr(response, "text", None), stage=stage)


class GeminiQualityTranslationProvider(_GeminiQualityStage):
    """Experimental initial translator with glossary and rolling context.

    The default production GeminiTranslationProvider is not changed or replaced.
    Rolling context is bounded to previously translated source/zh-TW pairs and is
    context-only: the model must return translations for the current batch only.
    """

    def __init__(
        self,
        *,
        model: str = "gemini-3.5-flash-lite",
        client: Any | None = None,
        provider: GeminiTranslationProvider | None = None,
        glossary: Mapping[str, Sequence[str]] | None = None,
        rolling_context_size: int = 0,
    ) -> None:
        super().__init__(model=model, client=client, provider=provider)
        if rolling_context_size < 0:
            raise ValueError("rolling_context_size must be >= 0")
        self.glossary = dict(glossary or {})
        self.rolling_context_size = rolling_context_size
        self._history: list[dict[str, str]] = []
        mode = []
        if self.glossary:
            mode.append("glossary")
        if self.rolling_context_size:
            mode.append(f"context{self.rolling_context_size}")
        suffix = "+".join(mode) if mode else "baseline-compatible"
        self.name = f"gemini-quality-v2:{self.model}:{suffix}"

    @property
    def rolling_context(self) -> tuple[dict[str, str], ...]:
        if not self.rolling_context_size:
            return ()
        return tuple(self._history[-self.rolling_context_size :])

    def reset_context(self) -> None:
        self._history.clear()

    def _build_prompt(self, texts: Sequence[str]) -> str:
        input_payload = [{"id": index, "text": text} for index, text in enumerate(texts)]
        context = list(self.rolling_context)
        glossary = _glossary_payload(self.glossary)
        return (
            "You are translating Japanese livestream subtitles into natural conversational "
            "Traditional Chinese used in Taiwan. Preserve meaning, uncertainty, jokes, "
            "nicknames, catchphrases, and spoken tone. Never invent unsupported facts or "
            "subjects. If ASR is fragmentary or uncertain, translate conservatively.\n\n"
            "FAN-SPEECH RULE: for recognizable sentence-final/catchphrase speech such as Japanese ぺこ, prefer romanized `peko` when it matches Hololive fan usage. Do not replace it with Chinese phonetic forms such as `佩克`; do not force every catchphrase into literal Chinese.\nGLOSSARY RULE: when a source glossary term appears, prefer one of its accepted "
            "zh-TW renderings when context permits; keep terminology consistent.\n"
            f"<glossary>{json.dumps(glossary, ensure_ascii=False)}</glossary>\n\n"
            "ROLLING CONTEXT RULE: previous pairs are context only. Do not output them and "
            "do not rewrite them. Use them only to resolve references and terminology.\n"
            f"<previous_context>{json.dumps(context, ensure_ascii=False)}</previous_context>\n\n"
            "TASK: translate only the current_input items. Return every current id exactly "
            "once, in a JSON array of objects with exactly id and translation. Do not merge, "
            "split, omit, annotate, or reorder items. Never return an empty translation; if an "
            "item is only a non-speech marker or music/sound cue, preserve that cue verbatim.\n"
            f"<current_input>{json.dumps(input_payload, ensure_ascii=False)}</current_input>"
        )

    def _repair_empty_translations(
        self,
        texts: Sequence[str],
        empty_ids: Sequence[int],
    ) -> dict[int, str]:
        """Retry only empty outputs once instead of failing the whole batch."""
        if not empty_ids:
            return {}
        retry_input = [
            {"id": item_id, "text": texts[item_id]}
            for item_id in empty_ids
        ]
        prompt = (
            "Repair only the empty subtitle translations below. Return one non-empty "
            "Traditional Chinese translation for every listed id. Preserve non-speech "
            "markers or sound/music cues verbatim when no translation is appropriate; "
            "never return an empty string. Keep intentional Hololive fan-speech such as "
            "sentence-final `peko` in romanization when supported by the source. "
            "Do not invent unsupported content.\n"
            f"<retry_input>{json.dumps(retry_input, ensure_ascii=False)}</retry_input>"
        )
        schema = {
            "type": "array",
            "minItems": len(retry_input),
            "maxItems": len(retry_input),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "translation"],
                "properties": {
                    "id": {"type": "integer"},
                    "translation": {"type": "string"},
                },
            },
        }
        decoded = self._generate(
            prompt,
            schema,
            stage="Gemini quality-v2 empty-translation repair",
        )
        expected_ids = set(empty_ids)
        repaired: dict[int, str] = {}
        for item in decoded:
            item_id = item.get("id")
            translated = item.get("translation")
            if (
                not isinstance(item_id, int)
                or item_id not in expected_ids
                or item_id in repaired
                or not isinstance(translated, str)
                or not translated.strip()
            ):
                raise TranslationProviderError(
                    "Gemini quality-v2 empty-translation repair returned invalid id/translation"
                )
            repaired[item_id] = translated.strip()
        if set(repaired) != expected_ids:
            raise TranslationProviderError(
                "Gemini quality-v2 empty-translation repair id mismatch"
            )
        return repaired

    def translate(
        self,
        texts: Sequence[str],
        *,
        target_language: str,
    ) -> Sequence[str]:
        if not texts:
            return ()
        _validate_target(target_language)
        prompt = self._build_prompt(texts)
        schema = {
            "type": "array",
            "minItems": len(texts),
            "maxItems": len(texts),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "translation"],
                "properties": {
                    "id": {"type": "integer"},
                    "translation": {"type": "string"},
                },
            },
        }
        decoded = self._generate(prompt, schema, stage="Gemini quality-v2 translation")
        translations: dict[int, str] = {}
        empty_ids: list[int] = []
        for item in decoded:
            item_id = item.get("id")
            translated = item.get("translation")
            if not isinstance(item_id, int) or not isinstance(translated, str):
                raise TranslationProviderError(
                    "Gemini quality-v2 translation items require integer id and string translation"
                )
            if item_id < 0 or item_id >= len(texts) or item_id in translations or item_id in empty_ids:
                raise TranslationProviderError(
                    f"Gemini quality-v2 translation returned invalid/duplicate id: {item_id}"
                )
            value = translated.strip()
            if not value:
                empty_ids.append(item_id)
                continue
            translations[item_id] = value

        returned_ids = set(translations) | set(empty_ids)
        if returned_ids != set(range(len(texts))):
            raise TranslationProviderError("Gemini quality-v2 translation id mismatch")
        if empty_ids:
            translations.update(self._repair_empty_translations(texts, empty_ids))

        ordered = tuple(translations[index] for index in range(len(texts)))
        if self.rolling_context_size:
            self._history.extend(
                {"source_text": source, "translated_text": translated}
                for source, translated in zip(texts, ordered, strict=True)
            )
            if len(self._history) > self.rolling_context_size:
                self._history = self._history[-self.rolling_context_size :]
        return ordered


@dataclass(frozen=True, slots=True)
class TranslationReviewFinding:
    id: int
    needs_revision: bool
    severity: str
    issues: tuple[str, ...]
    instruction: str


class GeminiTranslationReviewer(_GeminiQualityStage):
    """Structured quality estimation for existing translations."""

    def review(
        self,
        source_texts: Sequence[str],
        translations: Sequence[str],
        *,
        target_language: str = "zh-TW",
        glossary: Mapping[str, Sequence[str]] | None = None,
        previous_context: Sequence[Mapping[str, str]] = (),
        next_context: Sequence[Mapping[str, str]] = (),
    ) -> tuple[TranslationReviewFinding, ...]:
        _validate_target(target_language)
        if len(source_texts) != len(translations):
            raise ValueError("source_texts and translations must have equal length")
        if not source_texts:
            return ()

        items = [
            {"id": index, "source_text": source, "current_translation": translated}
            for index, (source, translated) in enumerate(
                zip(source_texts, translations, strict=True)
            )
        ]
        prompt = (
            "You are a strict Japanese→Taiwan Traditional Chinese subtitle quality reviewer. "
            "Evaluate the existing translation; do not rewrite it in this stage. Use the "
            "Japanese source as the authority. Be conservative: a stylistic preference alone "
            "is not a reason to revise an accurate, natural subtitle. Flag real meaning, "
            "omission, addition/hallucination, terminology, name/nickname, unnatural zh-TW, "
            "Japanese leakage, ASR uncertainty, or context-reference problems. Use previous/next "
            "context to resolve sentence fragments across caption boundaries, but review only the "
            "current items and never demand stylistic rewrites solely to make fragments standalone. "
            "ASR uncertainty by itself is NOT a reason to revise: if the current translation already "
            "plausibly repairs a malformed ASR token using context and preserves the intended meaning, "
            "accept it unchanged. Do not flag a translation merely to swap one plausible zh-TW synonym "
            "for another.\n"
            "FAN-SPEECH RULE: intentional romanized fandom speech such as sentence-final "
            "`peko` corresponding to Japanese ぺこ is acceptable and preferred over Chinese phonetic renderings such as `佩克`; it must not be flagged as "
            "Japanese leakage or unnatural zh-TW solely because it is preserved.\n"
            "If a translation is already acceptable, needs_revision must be false, severity "
            "must be none, issues must be empty, and instruction must be empty.\n"
            f"<glossary>{json.dumps(_glossary_payload(glossary), ensure_ascii=False)}</glossary>\n"
            f"<previous_context>{json.dumps(list(previous_context), ensure_ascii=False)}</previous_context>\n"
            f"<next_context>{json.dumps(list(next_context), ensure_ascii=False)}</next_context>\n"
            f"<items>{json.dumps(items, ensure_ascii=False)}</items>\n"
            "Return exactly one review object for every id."
        )
        schema = {
            "type": "array",
            "minItems": len(items),
            "maxItems": len(items),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "needs_revision",
                    "severity",
                    "issues",
                    "instruction",
                ],
                "properties": {
                    "id": {"type": "integer"},
                    "needs_revision": {"type": "boolean"},
                    "severity": {
                        "type": "string",
                        "enum": ["none", "minor", "major", "critical"],
                    },
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": sorted(_ALLOWED_ISSUES),
                        },
                    },
                    "instruction": {"type": "string"},
                },
            },
        }
        decoded = self._generate(prompt, schema, stage="Gemini translation review")
        findings: dict[int, TranslationReviewFinding] = {}
        for item in decoded:
            item_id = item.get("id")
            needs_revision = item.get("needs_revision")
            severity = item.get("severity")
            issues = item.get("issues")
            instruction = item.get("instruction")
            if (
                not isinstance(item_id, int)
                or not isinstance(needs_revision, bool)
                or severity not in _ALLOWED_SEVERITIES
                or not isinstance(issues, list)
                or any(issue not in _ALLOWED_ISSUES for issue in issues)
                or not isinstance(instruction, str)
            ):
                raise TranslationProviderError("Gemini translation review item contract mismatch")
            if item_id < 0 or item_id >= len(items) or item_id in findings:
                raise TranslationProviderError(
                    f"Gemini translation review returned invalid/duplicate id: {item_id}"
                )
            if not needs_revision:
                # Gemini can occasionally return stale explanatory metadata even when
                # its controlling decision is accept/False. Treat the boolean decision
                # as authoritative and normalize the non-operative fields instead of
                # aborting a long-running VOD review.
                severity = "none"
                issues = []
                instruction = ""
            if needs_revision and severity == "none":
                raise TranslationProviderError(
                    "Gemini translation review revision requires non-none severity"
                )
            findings[item_id] = TranslationReviewFinding(
                id=item_id,
                needs_revision=needs_revision,
                severity=severity,
                issues=tuple(issues),
                instruction=instruction.strip(),
            )
        if set(findings) != set(range(len(items))):
            raise TranslationProviderError("Gemini translation review id mismatch")

        # Deterministic leakage guard: model review may miss obvious copied kana.
        # Romanized fandom speech such as "peko" is Latin text and is unaffected.
        for item_id, translated in enumerate(translations):
            if not has_residual_japanese_kana(translated):
                continue
            current = findings[item_id]
            issues = list(current.issues)
            if "jp_leakage" not in issues:
                issues.append("jp_leakage")
            instruction = current.instruction or (
                "Remove or translate the residual Japanese kana while preserving "
                "meaning and any approved romanized fandom terms."
            )
            findings[item_id] = TranslationReviewFinding(
                id=item_id,
                needs_revision=True,
                severity=current.severity if current.severity != "none" else "minor",
                issues=tuple(issues),
                instruction=instruction,
            )
        return tuple(findings[index] for index in range(len(items)))


class GeminiTranslationPostEditor(_GeminiQualityStage):
    """Perform one selective post-edit pass over reviewer-flagged segments only."""

    def post_edit(
        self,
        source_texts: Sequence[str],
        translations: Sequence[str],
        findings: Sequence[TranslationReviewFinding],
        *,
        target_language: str = "zh-TW",
        glossary: Mapping[str, Sequence[str]] | None = None,
        context: Sequence[Mapping[str, str]] = (),
    ) -> tuple[str, ...]:
        _validate_target(target_language)
        if not (len(source_texts) == len(translations) == len(findings)):
            raise ValueError("source_texts, translations, and findings must have equal length")
        flagged = [finding for finding in findings if finding.needs_revision]
        if not flagged:
            return tuple(translations)

        items = [
            {
                "id": finding.id,
                "source_text": source_texts[finding.id],
                "current_translation": translations[finding.id],
                "review": {
                    "severity": finding.severity,
                    "issues": list(finding.issues),
                    "instruction": finding.instruction,
                },
            }
            for finding in flagged
        ]
        prompt = (
            "You are post-editing existing Japanese→Taiwan Traditional Chinese subtitles. "
            "This is not a fresh retranslation. Change only the flagged items below, and only "
            "when the reviewer finding is supported by the Japanese source/context. Context may "
            "contain neighboring unflagged subtitles and is reference-only; never output or rewrite "
            "context-only items. Preserve "
            "already-correct meaning and tone; never invent unsupported detail. If the current "
            "translation already satisfies the reviewer instruction or is already a plausible contextual "
            "repair of malformed ASR, return it EXACTLY unchanged. Make the smallest supported edit only; "
            "do not replace one plausible synonym with another. Never introduce a new semantic predicate, "
            "object, person, action, or relation that is not supported by source or neighboring context. "
            "Preserve intentional "
            "romanized fandom catchphrases such as sentence-final `peko` when supported by "
            "the Japanese source; prefer `peko` over Chinese phonetic forms such as `佩克`, and do not force them into literal Chinese. Return only the "
            "flagged ids.\n"
            f"<glossary>{json.dumps(_glossary_payload(glossary), ensure_ascii=False)}</glossary>\n"
            f"<context>{json.dumps(list(context), ensure_ascii=False)}</context>\n"
            f"<flagged_items>{json.dumps(items, ensure_ascii=False)}</flagged_items>"
        )
        schema = {
            "type": "array",
            "minItems": len(items),
            "maxItems": len(items),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "translation"],
                "properties": {
                    "id": {"type": "integer"},
                    "translation": {"type": "string"},
                },
            },
        }
        decoded = self._generate(prompt, schema, stage="Gemini selective post-edit")
        expected_ids = {finding.id for finding in flagged}
        replacements: dict[int, str] = {}
        for item in decoded:
            item_id = item.get("id")
            translation = item.get("translation")
            if (
                not isinstance(item_id, int)
                or item_id not in expected_ids
                or item_id in replacements
                or not isinstance(translation, str)
                or not translation.strip()
            ):
                raise TranslationProviderError(
                    "Gemini selective post-edit returned invalid id/translation"
                )
            replacements[item_id] = translation.strip()
        if set(replacements) != expected_ids:
            raise TranslationProviderError("Gemini selective post-edit id mismatch")

        result = list(translations)
        for item_id, value in replacements.items():
            result[item_id] = value
        return tuple(result)
