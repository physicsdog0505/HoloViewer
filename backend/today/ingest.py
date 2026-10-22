"""Bounded offline ingestion orchestration: never performs provider I/O itself."""
from dataclasses import dataclass, field
from .engine import normalize_video, VIDEO_ID, CHANNEL_ID
from .schedule import Budget

@dataclass(frozen=True)
class ApprovedRoster:
    version: str
    channels: frozenset[str]
    groups: dict = field(default_factory=dict)
    def __post_init__(self):
        if not self.version.strip() or not self.channels:
            raise ValueError("roster requires version and channels")
        if any(not CHANNEL_ID.fullmatch(channel) for channel in self.channels):
            raise ValueError("invalid roster channel ID")
        if any(ch not in self.channels or group not in {"hololive","holostars","mekpark","other"} for ch,group in self.groups.items()):
            raise ValueError("unapproved roster group")

@dataclass(frozen=True)
class IngestionResult:
    records: tuple
    attempted: int
    quota_units: int
    gap: bool
    failures: tuple
    needs_review: tuple

def ingest_batches(*, roster, pages, metadata, observed_at, budget=None,
                   used_units=0, max_pages_per_channel=2, reference_now=None):
    """pages maps allowed channel -> bounded pages of IDs; metadata is an injected callback.
    Quota consumed here models only metadata batches, NOT discovery page requests.
    Actual call metering must also reserve discovery requests before cloud activation.
    """
    budget = budget or Budget()
    if not 1 <= max_pages_per_channel <= budget.max_overlap_pages:
        raise ValueError("unbounded pages")
    ids, seen, errors, gap = [], set(), [], False
    for channel in sorted(roster.channels):
        channel_pages = pages.get(channel)
        if not channel_pages:
            gap = True
            errors.append((channel, "missing_coverage"))
            continue
        if len(channel_pages) > max_pages_per_channel:
            gap = True
            errors.append((channel, "truncated_pages"))
        for page in channel_pages[:max_pages_per_channel]:
            for ident in page:
                if ident not in seen:
                    ids.append(ident)
                    seen.add(ident)
    clean = []
    for ident in ids:
        if isinstance(ident, str) and VIDEO_ID.fullmatch(ident):
            clean.append(ident)
        else:
            gap = True
            errors.append((str(ident)[:20], "invalid_video_id"))
    if len(clean) > budget.max_candidates:
        gap = True
        errors.append(("roster", "candidate_limit"))
        clean = clean[:budget.max_candidates]
    records, quarantined, calls = [], [], 0
    for index in range(0, len(clean), 50):
        batch = clean[index:index + 50]
        if not budget.permits(used_units + calls, 1):
            gap = True
            errors.append(("provider", "quota_exhausted"))
            break
        calls += 1
        try:
            data = metadata(tuple(batch))
            if not isinstance(data, dict):
                raise ValueError("invalid_provider_response")
        except Exception:
            gap = True
            errors.append(("provider", "provider_failure"))
            continue
        for ident in batch:
            raw = data.get(ident)
            if raw is None:
                gap = True
                errors.append((ident, "missing_metadata"))
                continue
            try:
                normalized = normalize_video(raw, observed_at=observed_at,
                    approved_channels=roster.channels, reference_now=reference_now,
                    roster_version=roster.version, approved_groups=roster.groups)
            except (ValueError, TypeError):
                gap = True
                errors.append((ident, "bad_metadata"))
                continue
            if normalized is None:
                quarantined.append(ident)
                gap = True
                continue
            if normalized["video_id"] != ident:
                gap = True
                errors.append((ident, "identity_mismatch"))
                continue
            records.append(normalized)
    return IngestionResult(tuple(records), len(clean), calls, gap,
                           tuple(errors), tuple(quarantined))
