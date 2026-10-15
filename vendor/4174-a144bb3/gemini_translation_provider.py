"""Gemini text translation adapter for normalized subtitle batches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Any

from translation_pipeline import TranslationProviderError


class GeminiPreflightError(TranslationProviderError):
    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Gemini {stage} preflight failed")


class GeminiTranslationProvider:
    """Translate Japanese subtitle phrases into Traditional Chinese with Gemini."""

    def __init__(
        self,
        *,
        model: str = "gemini-3.5-flash-lite",
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
        generation_guard: Callable[[str, str], None] | None = None,
    ) -> None:
        self.model = model
        self.name = f"gemini:{model}"
        self._client = client
        self._client_factory = client_factory
        # Optional synchronous fail-closed pre-request hook for background jobs.
        self.generation_guard = generation_guard

    def _load_client(self) -> Any:
        if self._client is not None:
            return self._client
        factory = self._client_factory
        if factory is None:
            try:
                from google import genai  # type: ignore
            except ImportError as exc:
                raise TranslationProviderError(
                    "google-genai is not installed in this environment"
                ) from exc
            # The resumable runner owns retries; prevent nested SDK retry loops.
            factory = lambda: genai.Client(http_options={
                "timeout": 60_000, "retry_options": {"attempts": 1},
            })
        try:
            self._client = factory()
        except Exception as exc:
            raise TranslationProviderError(
                f"could not initialize Gemini client: {type(exc).__name__}: {exc}"
            ) from exc
        return self._client

    def preflight(self, *, target_language: str = "zh-TW") -> None:
        """Validate local configuration and model access before sending a transcript."""
        if target_language.lower() not in {"zh-tw", "zh_hant", "traditional-chinese"}:
            raise GeminiPreflightError("target_language")
        if not isinstance(self.model, str) or not self.model.strip():
            raise GeminiPreflightError("model_config")
        try:
            client = self._load_client()  # SDK + API key / Vertex configuration validation
        except TranslationProviderError as exc:
            stage = "sdk" if isinstance(exc.__cause__, ImportError) else "credentials_config"
            raise GeminiPreflightError(stage) from exc
        try:
            info = client.models.get(model=self.model)
            actions = getattr(info, "supported_actions", None)
            if isinstance(actions, list) and "generateContent" not in actions:
                raise TranslationProviderError("model does not support generateContent")
        except Exception as exc:
            raise GeminiPreflightError("model_access") from exc

    def translate(
        self,
        texts: Sequence[str],
        *,
        target_language: str,
    ) -> Sequence[str]:
        if not texts:
            return ()
        if target_language.lower() not in {"zh-tw", "zh_hant", "traditional-chinese"}:
            raise TranslationProviderError(
                f"GeminiTranslationProvider currently expects Traditional Chinese, got {target_language!r}"
            )

        indexed_input = [
            {"id": index, "text": text}
            for index, text in enumerate(texts)
        ]
        payload = json.dumps(indexed_input, ensure_ascii=False)
        prompt = (
            "Translate this ordered Japanese livestream subtitle batch into natural conversational Traditional Chinese used in Taiwan. "
            "Treat the full ordered batch as context: use neighboring lines to resolve pronouns, omitted subjects, jokes, references, and sentence fragments, while still returning one translation for each original item. "
            "Keep Hololive names, anime/work titles, character names, nicknames, catchphrases, and recurring terminology consistent across the entire batch. "
            "Prefer concise spoken subtitle phrasing over formal written Chinese. Preserve the speaker's tone and uncertainty. "
            "Never invent facts, explanations, subjects, or events that are not supported by the Japanese. If ASR wording is uncertain or fragmentary, translate conservatively instead of guessing. "
            "Do not merge, split, reorder, explain, annotate, or omit items. "
            "Return ONLY a JSON array of objects. Each object must contain exactly the input integer `id` "
            "and one string field `translation`. Return every id exactly once.\n"
            f"Input JSON: {payload}"
        )
        response_schema = {
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
        client = self._load_client()
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": response_schema,
                    "temperature": 0,
                },
            )
        except Exception as exc:
            raise TranslationProviderError(
                f"Gemini translation request failed: {type(exc).__name__}: {exc}"
            ) from exc

        text = getattr(response, "text", None)
        if not text:
            raise TranslationProviderError("Gemini translation returned no text")
        try:
            decoded = json.loads(text)
        except Exception as exc:
            raise TranslationProviderError(
                f"Gemini translation returned invalid JSON: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(decoded, list):
            raise TranslationProviderError("Gemini translation JSON must be an array")

        translations: dict[int, str] = {}
        for item in decoded:
            if not isinstance(item, dict):
                raise TranslationProviderError("Gemini translation items must be objects")
            item_id = item.get("id")
            translated = item.get("translation")
            if isinstance(item_id, str) and item_id.strip().isdigit():
                item_id = int(item_id.strip())
            if not isinstance(item_id, int) or not isinstance(translated, str):
                raise TranslationProviderError(
                    "Gemini translation items require integer id and string translation"
                )
            if item_id < 0 or item_id >= len(texts):
                raise TranslationProviderError(f"Gemini translation returned invalid id: {item_id}")
            if item_id in translations:
                raise TranslationProviderError(f"Gemini translation returned duplicate id: {item_id}")
            translated = translated.strip()
            if not translated:
                raise TranslationProviderError(f"Gemini translation returned empty translation for id: {item_id}")
            translations[item_id] = translated

        expected_ids = set(range(len(texts)))
        actual_ids = set(translations)
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            extra = sorted(actual_ids - expected_ids)
            raise TranslationProviderError(
                "Gemini translation id mismatch: "
                f"expected {len(texts)} items, got {len(translations)}; "
                f"missing_ids={missing}, extra_ids={extra}"
            )

        return tuple(translations[index] for index in range(len(texts)))
