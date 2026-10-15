"""Offline-only provider-neutral PTT Today/History contract for Issue #48.

No network, SQLite, Cloudflare, Collector, Publisher, or runtime process access occurs
here. Inputs are synthetic fixtures until a separately authorized provider adapter is
reviewed. Public fields in this module are contract candidates, not production proof.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Callable
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
MAX_RELAY_PAGE = 500
MAX_READ_BYTES = 512 * 1024
INITIAL_WINDOW = 300
_PUSH_ID_RE = re.compile(r"^ptt:v1:[0-9a-f]{64}$")
_AID_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class ContractError(ValueError):
    """Fail-closed contract violation."""


class SourceUnavailable(ContractError):
    """Provider-neutral source/day unavailable (never a successful empty feed)."""


def _parse_aware(iso: str, field: str) -> datetime:
    if not isinstance(iso, str) or not iso:
        raise ContractError(f"{field} is required")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{field} must be ISO-8601") from error
    if dt.tzinfo is None:
        raise ContractError(f"{field} requires timezone")
    return dt


def taipei_day(iso: str) -> str:
    return _parse_aware(iso, "timestamp").astimezone(TAIPEI).date().isoformat()


def normalize_public_aid(value: str) -> str:
    """Exact reviewed #311 normalization: strip Collector's leading '#' only."""
    if not isinstance(value, str):
        raise ContractError("aid must be text")
    aid = value.strip()
    if aid.startswith("#"):
        aid = aid[1:]
    if not _AID_RE.fullmatch(aid):
        raise ContractError("aid is invalid")
    return aid


def canonical_id(push: dict[str, Any]) -> str:
    """Byte-compatible with reviewed private PR #311 canonical_public_push_id()."""
    aid = normalize_public_aid(push.get("aid"))
    line = push.get("source_line")
    author = push.get("author")
    content = push.get("content")
    when = push.get("occurred_at")
    if type(line) is not int or line < 1:
        raise ContractError("source_line must be a positive integer")
    if not isinstance(author, str):
        raise ContractError("author must be text")
    if not isinstance(content, str):
        raise ContractError("content must be text")
    utc = _parse_aware(when, "occurred_at").astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wire = dumps([aid, line, author, utc, content], ensure_ascii=False, separators=(",", ":"))
    return "ptt:v1:" + sha256(wire.encode("utf-8")).hexdigest()


def history_completeness(
    manifest: dict[str, Any] | None,
    *,
    expected_day: str | None,
    expected_aids: set[str] | None,
    verify_authority: Callable[[dict[str, Any]], bool] | None = None,
) -> str:
    """Only independently accepted fixture evidence may grant COMPLETE offline.

    No caller complete flag, checksum self-consistency, title-only row, or empty day
    is considered authority. Production issuer/signature verification remains gated.
    """
    if not isinstance(manifest, dict):
        return "partial"
    aids = manifest.get("aids")
    if (
        not callable(verify_authority)
        or not verify_authority(manifest)
        or manifest.get("status") != "final-complete"
        or not isinstance(manifest.get("day"), str)
        or not isinstance(aids, list)
        or not aids
        or any(not isinstance(aid, str) for aid in aids)
        or len(aids) != len(set(aids))
        or expected_day is None
        or not expected_aids
    ):
        return "partial"
    normalized_expected = {normalize_public_aid(aid) for aid in expected_aids}
    normalized_manifest = {normalize_public_aid(aid) for aid in aids}
    if manifest["day"] != expected_day or normalized_manifest != normalized_expected:
        return "partial"
    return "complete"


@dataclass(frozen=True)
class InitialWindow:
    aid: str
    pushes: list[dict[str, Any]]
    checkpoint_cursor: int
    checked_at: str
    purged_through_cursor: int = 0
    history_gap: bool = False
    safe: bool = True


@dataclass(frozen=True)
class RelayPage:
    aid: str
    after_cursor: int
    next_cursor: int
    has_more: bool
    checked_at: str
    purged_through_cursor: int
    pushes: list[dict[str, Any]]
    history_gap: bool = False


class PttProvider(ABC):
    """Provider-neutral seam: 8788/UI must not know SQLite or D1 schemas."""

    @abstractmethod
    def aids_for_day(self, day: str) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def snapshot_for_day(self, day: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def initial_window(self, aid: str, *, limit: int) -> InitialWindow:
        """Return a safely assembled recent window plus future-delta checkpoint."""
        raise NotImplementedError

    @abstractmethod
    def relay_after(self, aid: str, *, after_cursor: int, limit: int) -> RelayPage:
        raise NotImplementedError


@dataclass
class SyntheticPttProvider(PttProvider):
    """In-memory provider used only by offline tests."""

    day_aids: dict[str, set[str]]
    snapshots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    relay_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    purged: dict[str, int] = field(default_factory=dict)
    checked_at: str = "2026-10-15T00:00:00Z"
    byte_limit: int = MAX_READ_BYTES
    tail_chunk_limit: int | None = None

    def aids_for_day(self, day: str) -> set[str]:
        return {normalize_public_aid(a) for a in self.day_aids.get(day, set())}

    def snapshot_for_day(self, day: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.snapshots.get(day, [])]

    def _page(self, aid: str, rows: list[dict[str, Any]], *, after: int, requested_limit: int) -> RelayPage:
        aid = normalize_public_aid(aid)
        if requested_limit < 1:
            raise ContractError("invalid relay limit")
        visible: list[dict[str, Any]] = []
        cap = min(requested_limit, MAX_RELAY_PAGE)
        for raw in rows[:cap]:
            row = dict(raw)
            probe = visible + [row]
            body = {
                "schema_version": 1,
                "next_cursor": row["cursor"],
                "has_more": False,
                "checked_at": self.checked_at,
                "history_gap": after < self.purged.get(aid, 0),
                "purged_through_cursor": self.purged.get(aid, 0),
                "pushes": probe,
            }
            if len(dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > self.byte_limit:
                break
            visible.append(row)
        has_more = len(rows) > len(visible)
        next_cursor = visible[-1]["cursor"] if visible else after
        return RelayPage(
            aid=aid,
            after_cursor=after,
            next_cursor=next_cursor,
            has_more=has_more,
            checked_at=self.checked_at,
            purged_through_cursor=self.purged.get(aid, 0),
            pushes=visible,
            history_gap=after < self.purged.get(aid, 0),
        )

    def initial_window(self, aid: str, *, limit: int) -> InitialWindow:
        aid = normalize_public_aid(aid)
        if limit < 1:
            raise ContractError("invalid initial limit")
        rows = sorted(self.relay_rows.get(aid, []), key=lambda row: row["cursor"])
        selected = [dict(row) for row in rows[-limit:]]
        return InitialWindow(
            aid=aid,
            pushes=selected,
            checkpoint_cursor=max((row["cursor"] for row in rows), default=0),
            checked_at=self.checked_at,
            purged_through_cursor=self.purged.get(aid, 0),
            history_gap=False,
            safe=True,
        )

    def relay_tail(self, aid: str, *, limit: int) -> RelayPage:
        """Raw synthetic tail page used only to prove unsafe bootstrap rejection."""
        aid = normalize_public_aid(aid)
        rows = sorted(self.relay_rows.get(aid, []), key=lambda row: row["cursor"])
        effective = min(limit, self.tail_chunk_limit) if self.tail_chunk_limit else limit
        selected = rows[-effective:]
        page = self._page(aid, selected, after=0, requested_limit=effective)
        older_exist = bool(selected) and rows[0]["cursor"] < selected[0]["cursor"]
        return RelayPage(**{**page.__dict__, "has_more": page.has_more or older_exist})

    def relay_after(self, aid: str, *, after_cursor: int, limit: int) -> RelayPage:
        aid = normalize_public_aid(aid)
        rows = [r for r in sorted(self.relay_rows.get(aid, []), key=lambda row: row["cursor"]) if r["cursor"] > after_cursor]
        return self._page(aid, rows, after=after_cursor, requested_limit=limit)


@dataclass
class TodayAdapter:
    day: str
    aids: set[str]
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    cursors: dict[str, int] = field(default_factory=dict)
    purged: dict[str, int] = field(default_factory=dict)
    last_checked_by_aid: dict[str, str] = field(default_factory=dict)
    freshness: str = "unknown"
    completeness: str = "partial"
    history_gap: bool = False
    source: str = "offline-contract"

    def __post_init__(self) -> None:
        try:
            parsed = date.fromisoformat(self.day)
            if parsed.isoformat() != self.day:
                raise ValueError("non-canonical date")
        except (TypeError, ValueError) as error:
            raise ContractError("day must be exact YYYY-MM-DD") from error
        normalized = {normalize_public_aid(aid) for aid in self.aids}
        if not normalized:
            raise ContractError("explicit verified AIDs required")
        self.aids = normalized
        for aid in self.aids:
            self.cursors.setdefault(aid, 0)
            self.purged.setdefault(aid, 0)

    @classmethod
    def from_provider(cls, provider: PttProvider, day: str) -> "TodayAdapter":
        aids = provider.aids_for_day(day)
        adapter = cls(day=day, aids=aids)
        adapter.merge_snapshot(provider.snapshot_for_day(day))
        return adapter

    def _stage_rows(self, pushes: Iterable[dict[str, Any]], *, base_rows: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        """Validate all rows and winner selection before mutating any adapter state."""
        staged = dict(self.rows if base_rows is None else base_rows)
        for raw in pushes:
            row = dict(raw)
            aid = normalize_public_aid(row.get("aid"))
            row["aid"] = aid
            if aid not in self.aids:
                raise ContractError("cross-thread AID")
            if taipei_day(row["occurred_at"]) != self.day:
                raise ContractError("cross-day push")
            if row.get("floor") is not None and (type(row["floor"]) is not int or row["floor"] < 1):
                raise ContractError("invalid display floor")
            identity = canonical_id(row)
            if row.get("push_id") not in (None, identity):
                raise ContractError("canonical push_id mismatch")
            row["push_id"] = identity
            row.setdefault("origin", "web")
            old = staged.get(identity)
            if old is None or (row["origin"] == "collector" and old.get("origin") != "collector"):
                staged[identity] = row
        return staged

    def merge_snapshot(self, pushes: Iterable[dict[str, Any]], *, collector_first: bool = True) -> None:
        """All-or-nothing application of one snapshot batch."""
        self.rows = self._stage_rows(pushes)

    def consumer_checkpoint(self) -> str:
        """Opaque, day-bound state token; provider cursors never exposed to UI.

        Offline in-memory token only. Production persistence/authentication is gated.
        """
        # A consumer page checkpoint changes when visible content changes, even
        # if the relay cursor vector does not (snapshot-only/Collector wins).
        visible = [(row["push_id"], row.get("origin"), row.get("floor"), row.get("kind"))
                   for row in self._ordered()]
        material = dumps(
            [self.day, sorted(self.cursors.items()), sorted(self.purged.items()), visible,
             self.completeness, self.history_gap],
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return "ptt:checkpoint:v1:" + sha256(material).hexdigest()

    def check_consumer_checkpoint(self, token: str, day: str) -> None:
        if day != self.day or not isinstance(token, str) or token != self.consumer_checkpoint():
            raise ContractError("expired, foreign-day or invalid checkpoint")

    def _ordered(self) -> list[dict[str, Any]]:
        return sorted(
            self.rows.values(),
            key=lambda r: (
                _parse_aware(r["occurred_at"], "occurred_at").astimezone(timezone.utc),
                r["aid"],
                r["source_line"],
                r["push_id"],
            ),
        )

    def read_initial(self, limit: int = INITIAL_WINDOW) -> list[dict[str, Any]]:
        if limit != INITIAL_WINDOW:
            raise ContractError("accepted initial window is 300")
        return self._ordered()[-INITIAL_WINDOW:]

    def read_after_key(self, key: str, limit: int = 200) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ContractError("page bound")
        ordered = self._ordered()
        for index, row in enumerate(ordered):
            if row["push_id"] == key:
                return ordered[index + 1:index + 1 + limit]
        self.history_gap = True
        self.completeness = "partial"
        return []

    def ingest_relay_page(self, page: RelayPage) -> None:
        aid = normalize_public_aid(page.aid)
        if aid not in self.aids:
            raise ContractError("invalid AID")
        if type(page.after_cursor) is not int or page.after_cursor < 0:
            raise ContractError("invalid after_cursor")
        if type(page.next_cursor) is not int or page.next_cursor < page.after_cursor:
            raise ContractError("regressive cursor")
        if page.history_gap != (page.after_cursor < page.purged_through_cursor):
            raise ContractError("retention gap flag mismatch")
        if page.after_cursor < self.purged.get(aid, 0) or page.history_gap:
            self.history_gap = True
            self.completeness = "partial"
            raise ContractError("retention gap / purged floor")
        if page.after_cursor != self.cursors.get(aid, 0):
            raise ContractError("expired or wrong replay cursor")
        if len(page.pushes) > MAX_RELAY_PAGE:
            raise ContractError("too many pushes")
        checked = _parse_aware(page.checked_at, "checked_at")
        last = page.after_cursor
        normalized_rows = []
        for raw in page.pushes:
            row = dict(raw)
            if normalize_public_aid(row.get("aid")) != aid or type(row.get("cursor")) is not int or row["cursor"] <= last:
                raise ContractError("out-of-order/cross-AID relay")
            last = row["cursor"]
            normalized_rows.append(row)
        if normalized_rows and page.next_cursor != last:
            raise ContractError("next cursor does not match page")
        if not normalized_rows and page.next_cursor != page.after_cursor:
            raise ContractError("empty page cursor mismatch")
        wire = {
            "schema_version": 1,
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "checked_at": page.checked_at,
            "history_gap": page.history_gap,
            "purged_through_cursor": page.purged_through_cursor,
            "pushes": normalized_rows,
        }
        if len(dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_READ_BYTES:
            raise ContractError("oversize response")
        staged = self._stage_rows(normalized_rows)
        self.rows = staged
        self.cursors[aid] = page.next_cursor
        self.purged[aid] = max(self.purged.get(aid, 0), page.purged_through_cursor)
        self.last_checked_by_aid[aid] = checked.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self.freshness = "fresh"
        if page.has_more:
            self.completeness = "partial"

    @staticmethod
    def reject_unsafe_tail_bootstrap(page: RelayPage) -> None:
        """Known bug guard: tail has_more cannot become a forward checkpoint."""
        if page.has_more:
            raise ContractError("tail has_more cannot establish initial checkpoint")

    def initialize_from_provider(self, provider: PttProvider, *, target: int = INITIAL_WINDOW) -> None:
        """Validate every AID window before committing any day-level state."""
        if not 1 <= target <= INITIAL_WINDOW:
            raise ContractError("initial limit")
        staged_rows = dict(self.rows)
        staged_cursors = dict(self.cursors)
        staged_purged = dict(self.purged)
        staged_checked = dict(self.last_checked_by_aid)
        gap = self.history_gap
        for aid in sorted(self.aids):
            window = provider.initial_window(aid, limit=target)
            if not window.safe:
                raise ContractError("provider initial window is not coverage-safe")
            if normalize_public_aid(window.aid) != aid:
                raise ContractError("cross-AID initial window")
            if len(window.pushes) > target:
                raise ContractError("initial window exceeds target")
            checked = _parse_aware(window.checked_at, "checked_at")
            previous = 0
            for row in window.pushes:
                if normalize_public_aid(row.get("aid")) != aid:
                    raise ContractError("cross-AID initialization row")
                cursor = row.get("cursor")
                if type(cursor) is not int or cursor <= previous:
                    raise ContractError("initial cursors must be strictly increasing")
                previous = cursor
            if type(window.checkpoint_cursor) is not int or window.checkpoint_cursor < previous:
                raise ContractError("initial checkpoint precedes visible rows")
            if type(window.purged_through_cursor) is not int or window.purged_through_cursor < 0:
                raise ContractError("invalid purge watermark")
            # _stage_rows reads self.rows, but no externally visible mutation occurs.
            staged_rows = self._stage_rows(window.pushes, base_rows=staged_rows)
            staged_cursors[aid] = window.checkpoint_cursor
            staged_purged[aid] = max(staged_purged.get(aid, 0), window.purged_through_cursor)
            staged_checked[aid] = checked.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            gap = gap or window.history_gap
        self.rows = staged_rows
        self.cursors = staged_cursors
        self.purged = staged_purged
        self.last_checked_by_aid = staged_checked
        self.history_gap = gap
        if gap:
            self.completeness = "partial"
        self.freshness = "fresh" if staged_checked else "unknown"

    def poll_provider(self, provider: PttProvider, *, page_limit: int = 200, max_pages_per_aid: int = 3) -> None:
        """Bounded delta polling: successful per-AID progress is retained on failure.

        Last-good rows/checkpoints remain valid, but freshness is globally stale
        and completeness partial if *any* provider call fails.
        """
        if not 1 <= page_limit <= MAX_RELAY_PAGE or not 1 <= max_pages_per_aid <= 3:
            raise ContractError("poll bounds")
        try:
            for aid in sorted(self.aids):
                for _ in range(max_pages_per_aid):
                    after = self.cursors.get(aid, 0)
                    page = provider.relay_after(aid, after_cursor=after, limit=page_limit)
                    self.ingest_relay_page(page)
                    if not page.has_more:
                        break
                else:
                    self.completeness = "partial"
        except Exception:
            self.freshness = "stale"
            self.completeness = "partial"
            raise

    def mark_fetch_failure(self) -> None:
        self.freshness = "stale"

    def freshness_at(self, now_iso: str, stale_after_seconds: int = 30) -> str:
        now = _parse_aware(now_iso, "now")
        if not self.last_checked_by_aid:
            return "unknown"
        oldest = min(_parse_aware(value, "checked_at") for value in self.last_checked_by_aid.values())
        if now < oldest:
            self.freshness = "unknown"
            raise ContractError("freshness clock regression")
        if (now - oldest).total_seconds() > stale_after_seconds:
            self.freshness = "stale"
        return self.freshness

    def roll_to(self, now_iso: str, aids: set[str]) -> "TodayAdapter":
        next_day = taipei_day(now_iso)
        return self if next_day == self.day else TodayAdapter(day=next_day, aids=aids)


PUBLIC_PUSH_FIELDS = (
    "push_id", "aid", "source_line", "kind", "author",
    "content", "occurred_at", "floor", "source_url",
)
_PTT_ARTICLE_RE = re.compile(
    r"^https://www\\.ptt\\.cc/bbs/C_Chat/M\\.[0-9]+\\.A\\.[A-Za-z0-9]+\\.html$"
)


def public_push(row: dict[str, Any]) -> dict[str, Any]:
    """Explicit consumer allowlist. Never return provider/relay internals."""
    # Older synthetic contract fixtures have no kind; preserve unknown as None
    # rather than fabricating a 推/噓/→ vote that was not observed.
    kind = row.get("kind")
    if kind is not None and kind not in ("推", "噓", "→"):
        raise ContractError("unsupported push kind")
    raw_url = row.get("source_url")
    url = raw_url if isinstance(raw_url, str) and _PTT_ARTICLE_RE.fullmatch(raw_url) else None
    visible = {key: row.get(key) for key in PUBLIC_PUSH_FIELDS}
    visible["kind"] = kind
    visible["source_url"] = url
    return visible


def consumer_envelope(checked: dict[str, str], freshness: str,
                      completeness: str, gap: bool, clock: str) -> tuple[dict[str, Any], dict[str, Any]]:
    last = min(checked.values()) if checked else None
    return ({"status": freshness, "last_success_at": last},
            {"status": completeness, "gap": gap})


@dataclass(frozen=True)
class PttTodayReadModel:
    schema_version: str
    day: str
    as_of: str
    freshness: dict[str, Any]
    completeness: dict[str, Any]
    checkpoint: str
    pushes: list[dict[str, Any]]
    page: dict[str, Any]


@dataclass(frozen=True)
class PttHistoryReadModel:
    schema_version: str
    day: str
    as_of: str
    freshness: dict[str, Any]
    completeness: dict[str, Any]
    checkpoint: str | None
    pushes: list[dict[str, Any]]
    page: dict[str, Any]


class PttConsumerReader:
    """Frozen #45 consumer seam, with backend-only cursor/AID operations hidden.

    This offline stateful adapter is not a durable authenticated provider.
    """

    def __init__(self, provider: PttProvider, *, clock: Callable[[], str] | None = None):
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._today: TodayAdapter | None = None
        # Offline-only opaque continuation registry. Durable, signed tokens
        # belong to a separately authorized production provider.
        self._history_tokens: dict[str, tuple[str, str, int]] = {}

    def read_today(self, day: str, checkpoint: str | None = None,
                   limit: int = INITIAL_WINDOW) -> PttTodayReadModel:
        if type(limit) is not int or not 1 <= limit <= INITIAL_WINDOW:
            raise ContractError("read limit")
        if self._today is None or self._today.day != day:
            if checkpoint is not None:
                raise ContractError("foreign day checkpoint")
            try:
                staged = TodayAdapter.from_provider(self._provider, day)
                staged.initialize_from_provider(self._provider)
            except Exception as error:
                raise SourceUnavailable("PTT source unavailable") from error
            self._today = staged
        elif checkpoint is not None:
            self._today.check_consumer_checkpoint(checkpoint, day)
            try:
                self._today.poll_provider(self._provider)
            except Exception:
                # The previous good rows are still returned and marked stale;
                # success is never fabricated for a partial day refresh.
                pass
        adapter = self._today
        assert adapter is not None
        clock = self._clock()
        try:
            adapter.freshness_at(clock)
        except ContractError:
            adapter.freshness = "unknown"
        ordered = adapter._ordered()
        pushes = [public_push(row) for row in ordered[-limit:]]
        freshness, completeness = consumer_envelope(adapter.last_checked_by_aid, adapter.freshness, adapter.completeness, adapter.history_gap, clock)
        return PttTodayReadModel(
            schema_version="public-consumer-v1", day=day, as_of=clock,
            freshness=freshness, completeness=completeness,
            checkpoint=adapter.consumer_checkpoint(),
            pushes=pushes,
            page={"limit": limit, "has_more": len(ordered) > limit,
                  "next_checkpoint": adapter.consumer_checkpoint()},
        )

    def read_history(self, day: str, page_request: dict[str, Any]) -> PttHistoryReadModel:
        """Forward pagination over a pinned day/snapshot generation.

        A token points to the *next offset*, unlike the snapshot checkpoint.
        Unknown/foreign-day/stale tokens fail closed. No integer offset is
        exposed to the consumer. The in-memory registry is deliberately not a
        production-grade restart-resumable checkpoint store.
        """
        if not isinstance(page_request, dict):
            raise ContractError("invalid history page request")
        limit = page_request.get("limit", 200)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ContractError("history page bound")
        try:
            aids = self._provider.aids_for_day(day)
            adapter = TodayAdapter(day, aids)
            adapter.merge_snapshot(self._provider.snapshot_for_day(day))
        except Exception as error:
            raise SourceUnavailable("PTT source unavailable") from error
        ordered = adapter._ordered()
        snapshot = adapter.consumer_checkpoint()
        token = page_request.get("checkpoint")
        if token is None:
            offset = 0
        else:
            if not isinstance(token, str) or token not in self._history_tokens:
                raise ContractError("unknown or expired history continuation")
            expected_day, expected_snapshot, offset = self._history_tokens[token]
            if expected_day != day or expected_snapshot != snapshot:
                raise ContractError("foreign-day or stale history continuation")
            if offset < 1 or offset >= len(ordered):
                raise ContractError("history continuation beyond snapshot")
        selected = ordered[offset:offset + limit]
        end = offset + len(selected)
        has_more = end < len(ordered)
        next_token = None
        if has_more:
            material = dumps([day, snapshot, end], ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
            next_token = "ptt:history-page:v1:" + sha256(material).hexdigest()
            self._history_tokens[next_token] = (day, snapshot, end)
        clock = self._clock()
        return PttHistoryReadModel(
            schema_version="public-consumer-v1", day=day, as_of=clock,
            freshness={"status": "unknown", "last_success_at": None},
            completeness={"status": "partial", "gap": False},
            checkpoint=snapshot, pushes=[public_push(row) for row in selected],
            page={"limit": limit, "has_more": has_more,
                  "next_checkpoint": next_token},
        )
