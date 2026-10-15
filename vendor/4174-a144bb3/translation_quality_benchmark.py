"""Benchmark helpers for Gemini translation quality v2 experiments (#198).

This module stays outside production routing. It compares provider variants on the
same transcript and scores deterministic QE fixtures without making network calls by
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from gemini_translation_quality import TranslationReviewFinding
from transcript_pipeline import TranscriptSegment
from translation_benchmark import TranslationBenchmarkReport, run_translation_benchmark
from translation_pipeline import TranslationProvider


@dataclass(frozen=True, slots=True)
class TranslationVariantResult:
    name: str
    report: TranslationBenchmarkReport

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "report": self.report.to_dict()}


def run_translation_variant_benchmark(
    segments: Sequence[TranscriptSegment],
    variants: Mapping[str, TranslationProvider],
    *,
    target_language: str = "zh-TW",
    max_segments: int = 20,
    max_chars: int = 2000,
    glossary: dict[str, Sequence[str]] | None = None,
) -> tuple[TranslationVariantResult, ...]:
    """Run named translation variants against the exact same transcript.

    Providers are supplied explicitly so callers control whether the benchmark is
    offline/fake or live. This helper never constructs a client or credential.
    """
    results: list[TranslationVariantResult] = []
    for name, provider in variants.items():
        reset = getattr(provider, "reset_context", None)
        if reset is not None:
            reset()
        report = run_translation_benchmark(
            segments,
            provider,
            target_language=target_language,
            max_segments=max_segments,
            max_chars=max_chars,
            glossary=glossary,
        )
        results.append(TranslationVariantResult(name=name, report=report))
    return tuple(results)


@dataclass(frozen=True, slots=True)
class QEBenchmarkReport:
    total: int
    expected_revision_count: int
    expected_accept_count: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    issue_match_count: int
    issue_match_denominator: int

    @property
    def revision_recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0

    @property
    def acceptance_specificity(self) -> float:
        denominator = self.true_negative + self.false_positive
        return self.true_negative / denominator if denominator else 1.0

    @property
    def false_positive_rate(self) -> float:
        denominator = self.true_negative + self.false_positive
        return self.false_positive / denominator if denominator else 0.0

    @property
    def false_negative_rate(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.false_negative / denominator if denominator else 0.0

    @property
    def issue_match_rate(self) -> float:
        return (
            self.issue_match_count / self.issue_match_denominator
            if self.issue_match_denominator
            else 1.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "expected_revision_count": self.expected_revision_count,
            "expected_accept_count": self.expected_accept_count,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "revision_recall": round(self.revision_recall, 4),
            "acceptance_specificity": round(self.acceptance_specificity, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "issue_match_count": self.issue_match_count,
            "issue_match_denominator": self.issue_match_denominator,
            "issue_match_rate": round(self.issue_match_rate, 4),
        }


def evaluate_qe_findings(
    fixture_segments: Sequence[Mapping[str, Any]],
    findings: Sequence[TranslationReviewFinding],
) -> QEBenchmarkReport:
    """Score reviewer decisions against a deterministic seeded fixture."""
    if len(fixture_segments) != len(findings):
        raise ValueError("fixture_segments and findings must have equal length")

    tp = fp = tn = fn = 0
    issue_matches = issue_denominator = 0
    expected_revision_count = 0

    for index, (fixture, finding) in enumerate(
        zip(fixture_segments, findings, strict=True)
    ):
        fixture_id = fixture.get("id")
        if fixture_id != index or finding.id != index:
            raise ValueError("fixture/findings ids must be contiguous and aligned")

        expected_revision = fixture.get("expected_needs_revision")
        if not isinstance(expected_revision, bool):
            raise ValueError("fixture expected_needs_revision must be boolean")
        expected_issue = fixture.get("expected_issue")
        if expected_issue is not None and not isinstance(expected_issue, str):
            raise ValueError("fixture expected_issue must be string or null")

        if expected_revision:
            expected_revision_count += 1
            if finding.needs_revision:
                tp += 1
            else:
                fn += 1
        else:
            if finding.needs_revision:
                fp += 1
            else:
                tn += 1

        if expected_revision and expected_issue:
            issue_denominator += 1
            if expected_issue in finding.issues:
                issue_matches += 1

    return QEBenchmarkReport(
        total=len(fixture_segments),
        expected_revision_count=expected_revision_count,
        expected_accept_count=len(fixture_segments) - expected_revision_count,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        issue_match_count=issue_matches,
        issue_match_denominator=issue_denominator,
    )


@dataclass(frozen=True, slots=True)
class PostEditDiffReport:
    total: int
    reviewer_flagged: int
    rewritten: int
    unflagged_changed: int

    @property
    def rewrite_rate(self) -> float:
        return self.rewritten / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "reviewer_flagged": self.reviewer_flagged,
            "rewritten": self.rewritten,
            "rewrite_rate": round(self.rewrite_rate, 4),
            "unflagged_changed": self.unflagged_changed,
        }


def evaluate_post_edit_diff(
    before: Sequence[str],
    after: Sequence[str],
    findings: Sequence[TranslationReviewFinding],
) -> PostEditDiffReport:
    """Measure how selective a post-edit pass actually was."""
    if not (len(before) == len(after) == len(findings)):
        raise ValueError("before, after, and findings must have equal length")
    rewritten = 0
    unflagged_changed = 0
    flagged = 0
    for old, new, finding in zip(before, after, findings, strict=True):
        if finding.needs_revision:
            flagged += 1
        if old != new:
            rewritten += 1
            if not finding.needs_revision:
                unflagged_changed += 1
    return PostEditDiffReport(
        total=len(before),
        reviewer_flagged=flagged,
        rewritten=rewritten,
        unflagged_changed=unflagged_changed,
    )
