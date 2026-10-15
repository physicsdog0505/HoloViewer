"""Reusable quality-v2 review and selective post-edit batching.

The benchmark CLI and subtitle acceptance component share this module so the
quality algorithm is not owned by a page or test harness.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from gemini_translation_quality import TranslationReviewFinding
from translation_pipeline import TranslationProviderError


def context_pairs(
    sources: Sequence[str],
    translations: Sequence[str],
    indexes: range,
) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "source_text": sources[index],
            "translated_text": translations[index],
        }
        for index in indexes
    )


def previous_context(
    sources: Sequence[str],
    translations: Sequence[str],
    start: int,
    *,
    context_size: int,
) -> tuple[dict[str, str], ...]:
    if context_size <= 0:
        return ()
    return context_pairs(
        sources,
        translations,
        range(max(0, start - context_size), start),
    )


def next_context(
    sources: Sequence[str],
    translations: Sequence[str],
    end: int,
    *,
    context_size: int,
) -> tuple[dict[str, str], ...]:
    if context_size <= 0:
        return ()
    return context_pairs(
        sources,
        translations,
        range(end, min(len(sources), end + context_size)),
    )


def review_in_batches(
    reviewer,
    sources: Sequence[str],
    translations: Sequence[str],
    *,
    batch_size: int,
    context_size: int = 2,
    glossary: Mapping[str, Sequence[str]] | None = None,
    request_interval_seconds: float = 0.0,
    sleep=time.sleep,
) -> tuple[TranslationReviewFinding, ...]:
    """Bound QE requests and remap local reviewer ids to global ids."""
    if batch_size <= 0:
        raise ValueError("QE batch size must be > 0")
    if request_interval_seconds < 0:
        raise ValueError("request interval must be >= 0")
    findings: list[TranslationReviewFinding] = []
    made_request = False
    for start in range(0, len(sources), batch_size):
        end = min(len(sources), start + batch_size)
        local = None
        last_error: TranslationProviderError | None = None
        for attempt in range(2):
            if (made_request or attempt) and request_interval_seconds:
                sleep(request_interval_seconds)
            try:
                local = reviewer.review(
                    sources[start:end],
                    translations[start:end],
                    glossary=glossary,
                    previous_context=previous_context(
                        sources, translations, start, context_size=context_size
                    ),
                    next_context=next_context(
                        sources, translations, end, context_size=context_size
                    ),
                )
            except TranslationProviderError as exc:
                last_error = exc
                # A long VOD should not be discarded because one structured QE
                # response contains duplicate/missing ids or other transient
                # contract noise. Retry the same bounded batch once.
                if attempt == 1:
                    raise
                continue
            else:
                made_request = True
                break
        if local is None:
            assert last_error is not None
            raise last_error
        findings.extend(
            TranslationReviewFinding(
                id=start + item.id,
                needs_revision=item.needs_revision,
                severity=item.severity,
                issues=item.issues,
                instruction=item.instruction,
            )
            for item in local
        )
    return tuple(findings)


def post_edit_in_batches(
    editor,
    sources: Sequence[str],
    translations: Sequence[str],
    findings: Sequence[TranslationReviewFinding],
    *,
    batch_size: int,
    context_size: int = 2,
    glossary: Mapping[str, Sequence[str]] | None = None,
    request_interval_seconds: float = 0.0,
    sleep=time.sleep,
) -> tuple[str, ...]:
    """Post-edit bounded chunks while preserving unflagged text byte-for-byte."""
    if batch_size <= 0:
        raise ValueError("post-edit batch size must be > 0")
    if request_interval_seconds < 0:
        raise ValueError("request interval must be >= 0")
    if not (len(sources) == len(translations) == len(findings)):
        raise ValueError("sources, translations, and findings must have equal length")

    revised = list(translations)
    made_request = False
    for start in range(0, len(sources), batch_size):
        end = min(len(sources), start + batch_size)
        local_findings = tuple(
            TranslationReviewFinding(
                id=item.id - start,
                needs_revision=item.needs_revision,
                severity=item.severity,
                issues=item.issues,
                instruction=item.instruction,
            )
            for item in findings[start:end]
        )
        if not any(item.needs_revision for item in local_findings):
            continue
        context = (
            *previous_context(
                sources, translations, start, context_size=context_size
            ),
            *next_context(
                sources, translations, end, context_size=context_size
            ),
        )
        local_revised = None
        last_error: TranslationProviderError | None = None
        for attempt in range(2):
            if (made_request or attempt) and request_interval_seconds:
                sleep(request_interval_seconds)
            try:
                local_revised = editor.post_edit(
                    sources[start:end],
                    translations[start:end],
                    local_findings,
                    glossary=glossary,
                    context=context,
                )
            except TranslationProviderError as exc:
                last_error = exc
                # Structured post-edit output can occasionally contain an invalid
                # or duplicate id. Retry the same bounded batch once, matching QE.
                if attempt == 1:
                    raise
                continue
            else:
                made_request = True
                break
        if local_revised is None:
            assert last_error is not None
            raise last_error
        revised[start:end] = local_revised
    return tuple(revised)
