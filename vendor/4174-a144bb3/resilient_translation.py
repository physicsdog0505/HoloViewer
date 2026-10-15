"""Atomic local sidecars for bounded, resumable translation (no database)."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from translation_pipeline import build_translation_batches, TranslationProviderError


def translation_identity(segments, provider, target_language, max_segments, max_chars):
    payload = {
        "source": [[s.start_ms, s.end_ms, s.source_text, s.provider] for s in segments],
        "provider": provider.name, "target_language": target_language,
        "max_segments": max_segments, "max_chars": max_chars,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def checkpoint_path(segments, provider, *, base_dir=Path("data/watchalong/translations"),
                    target_language="zh-TW", max_segments=20, max_chars=2000):
    return Path(base_dir) / (translation_identity(segments, provider, target_language, max_segments, max_chars) + ".json")


def _save(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after a complete write; interrupted writes leave the old checkpoint intact.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_state(segments, provider, path, *, target_language="zh-TW", max_segments=20, max_chars=2000):
    identity = translation_identity(segments, provider, target_language, max_segments, max_chars)
    batches = build_translation_batches(segments, max_segments=max_segments, max_chars=max_chars)
    state = {"version": 1, "identity": identity, "status": "not_started", "failure": None,
             "batches": [{"start": b.start_index, "end": b.end_index, "status": "not_started",
                          "attempts": 0, "translations": None, "failure": None} for b in batches]}
    if not Path(path).exists():
        return state
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or saved.get("version") != 1 or saved.get("identity") != identity:
        raise ValueError("translation checkpoint configuration/source mismatch")
    if saved.get("status") not in {"not_started", "generating", "ready", "failed"}:
        raise ValueError("translation checkpoint status mismatch")
    if not isinstance(saved.get("batches"), list) or len(saved["batches"]) != len(batches):
        raise ValueError("translation checkpoint batch mismatch")
    for item, batch in zip(saved["batches"], batches, strict=True):
        if not isinstance(item, dict) or not isinstance(item.get("attempts"), int) or item["attempts"] < 0:
            raise ValueError("translation checkpoint attempts mismatch")
        if (item["start"], item["end"]) != (batch.start_index, batch.end_index):
            raise ValueError("translation checkpoint range mismatch")
        if item["status"] not in {"not_started", "generating", "ready", "failed"}:
            raise ValueError("translation checkpoint status mismatch")
        values = item["translations"]
        if item["status"] == "ready":
            if not isinstance(values, list) or len(values) != len(batch.source_texts) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError("translation checkpoint output mismatch")
        elif values is not None:
            raise ValueError("unfinished batch cannot contain translations")
    return saved


def partial_segments(segments, state):
    """One subtitle per source, including untranslated lines beyond the ready prefix."""
    result = [replace(s, translated_text=None) for s in segments]
    for batch in state["batches"]:
        if batch["status"] == "ready":
            for index, text in enumerate(batch["translations"], batch["start"]):
                result[index] = replace(segments[index], translated_text=text)
    return tuple(result)


def _failure(exc):
    current = exc
    codes = []
    messages = []
    while current is not None:
        codes.extend([getattr(current, "code", None), getattr(current, "status_code", None)])
        messages.append(str(current).lower())
        current = current.__cause__
    text = " ".join(messages)
    limited = 429 in codes or "429" in text or "resource_exhausted" in text or "quota" in text or "rate limit" in text
    transient = limited or any(code in {500, 502, 503, 504} for code in codes)
    # Keep provider exception messages (which may contain request/config secrets) out of persisted/UI state.
    return {"kind": "rate_limit_or_quota" if limited else "provider_error", "retryable": transient,
            "message": "Provider rate limit/quota reached" if limited else "Provider request or response validation failed"}


def translate_resumable(segments, provider, *, path, target_language="zh-TW", max_segments=20,
                        max_chars=2000, max_attempts=3, backoff_seconds=2.0,
                        max_backoff_seconds=30.0, request_interval_seconds=0.0,
                        sleep=time.sleep, on_progress=None, batch_order=None,
                        max_batches_per_invocation=None):
    """Retry budget is per explicit invocation; successful batches never run again."""
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    if not target_language.strip():
        raise ValueError("target_language must not be empty")
    if any(not math.isfinite(v) or v < 0 for v in (backoff_seconds, max_backoff_seconds, request_interval_seconds)):
        raise ValueError("delays must be finite and >= 0")
    state = load_state(segments, provider, path, target_language=target_language,
                       max_segments=max_segments, max_chars=max_chars)
    batch_count = len(state["batches"])
    if max_batches_per_invocation is not None:
        if (
            isinstance(max_batches_per_invocation, bool)
            or not isinstance(max_batches_per_invocation, int)
            or max_batches_per_invocation <= 0
        ):
            raise ValueError("max_batches_per_invocation must be a positive integer")
    if batch_order is None:
        ordered_indexes = tuple(range(batch_count))
    else:
        ordered_indexes = tuple(batch_order)
        if (
            any(
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= batch_count
                for index in ordered_indexes
            )
            or len(set(ordered_indexes)) != len(ordered_indexes)
        ):
            raise ValueError("batch_order must contain unique valid batch indexes")

    def publish():
        _save(path, state)
        if on_progress:
            on_progress(state)

    if all(b["status"] == "ready" for b in state["batches"]):
        if state["status"] != "ready":
            state.update(status="ready", failure=None)
            publish()
        return state
    try:
        preflight = getattr(provider, "preflight", None)
        if preflight:
            preflight(target_language=target_language)
    except Exception as exc:
        stage = getattr(exc, "stage", "configuration")
        if stage not in {"sdk", "credentials_config", "model_config", "model_access", "target_language"}:
            stage = "configuration"
        state.update(status="failed", failure={"kind": "preflight", "stage": stage, "retryable": False,
                                               "message": f"Gemini preflight failed ({stage}): {_failure(exc)['message']}",
                                               "cause_kind": _failure(exc)["kind"]})
        publish()
        return state
    state.update(status="generating", failure=None)
    made_request = False
    completed_batches = 0
    for batch_index in ordered_indexes:
        batch = state["batches"][batch_index]
        if batch["status"] == "ready":
            continue
        if (
            max_batches_per_invocation is not None
            and completed_batches >= max_batches_per_invocation
        ):
            break
        for attempt in range(max_attempts):
            if made_request and request_interval_seconds:
                sleep(request_interval_seconds)
            batch.update(status="generating", failure=None)
            batch["attempts"] += 1
            publish()
            made_request = True
            try:
                response = tuple(provider.translate(tuple(s.source_text for s in segments[batch["start"]:batch["end"]]), target_language=target_language))
                if len(response) != batch["end"] - batch["start"] or any(not isinstance(v, str) or not v.strip() for v in response):
                    raise TranslationProviderError("response count/type mismatch")
            except Exception as exc:
                failure = _failure(exc)
                batch.update(status="failed", failure=failure)
                state.update(status="failed", failure=failure)
                publish()
                if not failure["retryable"] or attempt + 1 == max_attempts:
                    return state
                sleep(min(max_backoff_seconds, backoff_seconds * 2 ** attempt))
                state.update(status="generating", failure=None)
            else:
                batch.update(status="ready", translations=[v.strip() for v in response], failure=None)
                completed_batches += 1
                publish()
                break
    if all(batch["status"] == "ready" for batch in state["batches"]):
        state.update(status="ready", failure=None)
    else:
        state.update(status="generating", failure=None)
    publish()
    return state
