"""Client 今日 homepage backed only by persisted local discovery evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from channel_push_discovery import (
    ChannelPushStore,
    cards_for_day,
    merge_cards,
    statuses_for_day,
)
from client_runtime import client_runtime_root
from client_collab_candidates import CollabCandidate, detect_collab_candidates
from client_support_colors import EXPORT_NAME, accent_style as exported_accent_style, load_support_colors
from client_stream_catalog import load_client_catalog_metadata, load_client_catalog_streams
from client_ui_shell import client_document
from frontend_stream_discovery import build_discovery_cards, hidden_reason
from frontend_time import TAIPEI
from live_stream_discovery import LiveDiscoveryCache
from today_stream_status import load_status_snapshot, stream_state
from youtube_metadata import YoutubeVideo


@dataclass(frozen=True, slots=True)
class HomeStream:
    video_id: str
    title: str
    channel_title: str
    start_label: str
    state: str
    source_label: str = ""
    channel_id: str = ""
    avatar_url: str = ""
    group: str = "hololive"
    start_at: datetime | None = None


STATUS_FRESHNESS = timedelta(minutes=20)
TODAY_ROLLOVER_HOUR = 6


def _today_source_days(current: datetime) -> tuple[date, ...]:
    """Keep the previous day's discovery evidence through the overnight window.

    After midnight many Hololive streams are still the same viewing session.
    Before 06:00 Taipei, read both yesterday and today so late-night streams do
    not disappear while newly-started post-midnight streams can still appear.
    """
    local = current.astimezone(TAIPEI)
    today = local.date()
    if local.hour < TODAY_ROLLOVER_HOUR:
        return (today - timedelta(days=1), today)
    return (today,)


def _snapshot_day(current: datetime) -> date:
    local = current.astimezone(TAIPEI)
    return (
        local.date() - timedelta(days=1)
        if local.hour < TODAY_ROLLOVER_HOUR
        else local.date()
    )

# Official penlight color names, translated into accessible UI text colors.
# Unknown/newer talents fall back to the normal muted label until verified.
_CHANNEL_ACCENT_RULES = (
    (("ロボ子", "ROBOCO"), "#d85a8a"),
    (("ときのそら", "TOKINO SORA"), "#397fc4"),
    (("AZKI",), "#c94a52"),
    (("さくらみこ", "SAKURA MIKO"), "#dc6f9f"),
    (("アキ・ローゼンタール", "AKI ROSENTHAL"), "#69a56f"),
    (("白上フブキ", "SHIRAKAMI FUBUKI"), "#4b97c8"),
    (("夏色まつり", "NATSUIRO MATSURI"), "#d87932"),
    (("百鬼あやめ", "NAKIRI AYAME"), "#c84b55"),
    (("癒月ちょこ", "YUZUKI CHOCO", "CHOCO CH."), "#d85a8a"),
    (("大空スバル", "OOZORA SUBARU"), "#a68118"),
    (("大神ミオ", "OOKAMI MIO"), "#69a56f"),
    (("兎田ぺこら", "USADA PEKORA"), "#4b97c8"),
    (("不知火フレア", "SHIRANUI FLARE"), "#d87932"),
    (("白銀ノエル", "SHIROGANE NOEL"), "#7d7d7d"),
    (("宝鐘マリン", "HOUSHOU MARINE"), "#c84b55"),
    (("天音かなた", "AMANE KANATA"), "#4b97c8"),
    (("常闇トワ", "TOKOYAMI TOWA"), "#7751a8"),
    (("雪花ラミィ", "YUKIHANA LAMY"), "#4b97c8"),
    (("獅白ぼたん", "SHISHIRO BOTAN"), "#7d7d7d"),
    (("尾丸ポルカ", "OMARU POLKA"), "#c84b55"),
)


def _channel_style(item: HomeStream) -> str:
    """Prefer audited channel-ID colors; retain old appearance before export arrives."""
    root = client_runtime_root()
    colors = load_support_colors(root)
    if (root / EXPORT_NAME).is_file():
        return exported_accent_style(item.channel_id, colors)
    accent = _channel_accent(item.channel_title or "")
    return f' style="--member-accent:{accent}"' if accent else ""

def _channel_accent(channel_title: str) -> str:
    haystack = channel_title.upper()
    for needles, color in _CHANNEL_ACCENT_RULES:
        if any(needle.upper() in haystack for needle in needles):
            return color
    return ""


_HOLOSTARS_TOKENS = (
    "HOLOSTARS", "ホロスターズ", "ホロスタ", "UPROAR",
    "KANADE IZURU", "奏手イヅル",
    "HANASAKI MIYABI", "花咲みやび",
    "ARURANDEISU", "アルランディス",
    "RIKKA", "律可",
    "ASTEL LEDA", "アステル・レダ",
    "YUKOKU ROBERU", "夕刻ロベル", "ROBERU CH.",
    "KISHIDO TEMMA", "岸堂天真",
    "ARAGAMI OGA", "荒咬オウガ",
    "KAGEYAMA SHIEN", "影山シエン",
    "YATOGAMI FUMA", "夜十神封魔",
    "UTSUGI UYU", "羽継烏有",
    "MINASE RIO", "水無世燐央",
    "REGIS ALTARE", "リージス・アルテア",
    "AXEL SYRIOS", "アクセル・シリオス",
    "GAVIS BETTEL", "ガビス・ベッテル",
    "MACHINA X FLAYON", "マキナ・X・フレオン",
    "BANZOIN HAKKA", "万象院ハッカ",
    "JOSUIJI SHINRI", "定水寺シンリ",
    "JURARD T REXFORD", "ジュラルド・ティー・レクスフォード",
    "GOLDBULLET", "ゴールドブレット",
    "OCTAVIO", "オクタビオ",
    "CRIMZON RUZE", "クリムゾン・ルーズ",
)


_MEKPARK_TOKENS = (
    "MEKPARK",
    "ACHRORA",
    "UNIT B",
)


def _load_hololive_channel_ids(root: Path) -> set[str]:
    path = root / "hololive_channels.prototype.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return set()
    channels = payload.get("channels", []) if isinstance(payload, dict) else []
    return {str(channel_id) for channel_id in channels if channel_id}


def _stream_group(
    channel_title: str,
    source_label: str = "",
    *,
    channel_id: str = "",
    hololive_channel_ids: set[str] | None = None,
) -> str:
    haystack = f"{channel_title} {source_label}".upper()
    if any(token.upper() in haystack for token in _HOLOSTARS_TOKENS):
        return "holostars"
    if any(token in haystack for token in _MEKPARK_TOKENS):
        return "mekpark"
    if channel_id and hololive_channel_ids and channel_id in hololive_channel_ids:
        return "hololive"
    # Some freshly discovered streams can reach the Client before their Catalog
    # channel_id has been hydrated. An explicit official channel title marker is
    # safe evidence; unlike the old fallback, arbitrary named channels are not
    # assumed to be Hololive.
    if "HOLOLIVE" in haystack or "ホロライブ" in haystack:
        return "hololive"
    return "other"


_HIGHLIGHT_RULES = (
    (120, "三期生告知", ("3期生", "三期生")),
    (105, "重大告知", ("重大告知", "重要告知", "IMPORTANT ANNOUNCEMENT", "BIG ANNOUNCEMENT")),
    (100, "初配信", ("DEBUT", "RE-DEBUT", "初配信", "デビュー")),
    (95, "周年", ("ANNIVERSARY", "周年", "記念配信")),
    (92, "新衣裝", ("NEW OUTFIT", "OUTFIT REVEAL", "新衣装", "新衣裝", "衣装お披露目", "新衣装お披露目")),
    (90, "生日", ("誕生日", "BIRTHDAY", "生日")),
    (85, "3D LIVE", ("3D LIVE", "3DLIVE", "3Dライブ")),
    (75, "大型聯動", ("大型コラボ", "大型聯動", "COLLAB", "コラボ")),
    (65, "歌回", ("歌枠", "歌回", "KARAOKE", "SINGING STREAM", "SINGING")),
    (60, "新造型", ("NEW HAIRSTYLE", "髪型お披露目", "NEW MODEL", "MODEL REVEAL", "LIVE2D")),
)


def _highlight_match(item: HomeStream) -> tuple[int, str]:
    title = " ".join(part for part in (item.title, item.source_label) if part).upper()
    best = (0, "")
    for score, label, keywords in _HIGHLIGHT_RULES:
        matched = any(keyword.upper() in title for keyword in keywords)
        if label == "三期生告知":
            matched = matched and any(
                token in title
                for token in ("告知", "重大", "終了", "結束", "ANNOUNCEMENT")
            )
        if matched and score > best[0]:
            best = (score, label)
    if item.state == "live" and best[0]:
        best = (best[0] + 5, best[1])
    return best


def select_home_highlight(*groups: list[HomeStream]) -> tuple[HomeStream, str] | None:
    """Pick one high-signal event from today's already-loaded runtime data."""

    candidates: list[tuple[int, HomeStream, str]] = []
    for group in groups:
        for item in group:
            score, label = _highlight_match(item)
            if score:
                candidates.append((score, item, label))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1].start_label, row[1].video_id), reverse=True)
    _score, item, label = candidates[0]
    return item, label



def select_home_highlights(
    *groups: list[HomeStream],
    limit: int = 6,
    collab_by_video: dict[str, CollabCandidate] | None = None,
) -> list[tuple[HomeStream, str]]:
    """Return event-distinct high-signal LIVE/upcoming streams for the carousel.

    Multiple POVs from one detected collab consume one carousel slot. The best
    scoring POV becomes that event's representative instead of letting a large
    collab crowd every other recommendation out.
    """
    collab_by_video = collab_by_video or {}
    candidates: list[tuple[int, HomeStream, str]] = []
    seen_videos: set[str] = set()
    for group in groups:
        for item in group:
            if item.video_id in seen_videos:
                continue
            seen_videos.add(item.video_id)
            if item.state not in {"live", "upcoming", "waiting"}:
                continue
            score, label = _highlight_match(item)
            if score:
                candidates.append((score, item, label))
    candidates.sort(key=lambda row: (-row[0], row[1].video_id))

    selected: list[tuple[HomeStream, str]] = []
    seen_events: set[str] = set()
    for _score, item, label in candidates:
        collab = collab_by_video.get(item.video_id)
        if collab is not None and len(collab.video_ids) > 1:
            event_key = collab.event_id or (
                collab.event_key + ":" + ",".join(sorted(collab.video_ids))
            )
            if event_key in seen_events:
                continue
            seen_events.add(event_key)
        selected.append((item, label))
        if len(selected) >= limit:
            break
    return selected


def _home_announcement_strip(highlights: list[tuple[HomeStream, str]]) -> str:
    announcements = [(item, label) for item, label in highlights if label in {"生日", "重大告知", "三期生告知"}]
    if not announcements:
        return ""
    messages = []
    for item, label in announcements:
        link = "/custom-view/session?" + urlencode([("stream", item.video_id), ("layout", "auto"), ("primary", "0"), ("audio", "0")])
        messages.append(f'<a href="{escape(link, quote=True)}"><strong>{escape(label)}</strong> · {escape(item.channel_title or "Hololive")}：{escape(item.title)}</a>')
    entries = ''.join(
        f'<span class="announcement-entry" data-announcement-index="{index}"'
        + (' hidden' if index else '') + f'>{message}</span>'
        for index, message in enumerate(messages)
    )
    return ('<aside class="home-announcements" aria-label="生日及重要直播消息">'
            '<span class="announcement-heading">📣 最新提醒</span>'
            f'<div class="announcement-messages" data-announcement-count="{len(messages)}">'
            f'<div class="announcement-track">{entries}</div></div></aside>')


def _home_highlight_carousel(
    highlights: list[tuple[HomeStream, str]],
    collab_by_video: dict[str, CollabCandidate] | None = None,
) -> str:
    if not highlights:
        return ""
    cards = []
    for index, (item, label) in enumerate(highlights):
        card = _highlight_card(item, label, (collab_by_video or {}).get(item.video_id))
        # Keep the existing vetted card markup; only carousel controls are new.
        start = card.index('<a class="home-highlight"')
        end = card.index('</a>', start) + len('</a>')
        cards.append(f'<div class="highlight-slide" data-slide="{index}"' + (' hidden' if index else '') + '>' + card[start:end] + '</div>')
    controls = ''
    if len(cards) > 1:
        dots = ''.join(f'<button type="button" class="highlight-dot{" active" if i == 0 else ""}" data-slide-to="{i}" aria-label="顯示第 {i+1} 則重點"></button>' for i in range(len(cards)))
        controls = f'<div class="highlight-controls"><button type="button" class="highlight-prev" aria-label="上一則重點">‹</button><div class="highlight-dots">{dots}</div><button type="button" class="highlight-next" aria-label="下一則重點">›</button></div>'
    return '<section class="section highlight-section"><div class="section-head"><div><h2>近期焦點</h2></div></div><div class="highlight-carousel" aria-label="近期焦點輪播">' + ''.join(cards) + controls + '</div></section>'


def _highlight_card(
    item: HomeStream,
    label: str,
    collab: CollabCandidate | None = None,
) -> str:
    if collab is not None and len(collab.video_ids) > 1:
        href = "/collab/session?" + urlencode(
            [("collab", collab.event_key)]
            + [("stream", video_id) for video_id in collab.video_ids]
        )
    else:
        href = "/custom-view/session?" + urlencode(
            [("stream", item.video_id), ("layout", "auto"), ("primary", "0"), ("audio", "0")]
        )
    thumb = f"https://i.ytimg.com/vi/{escape(item.video_id)}/hqdefault.jpg"
    state_label = {
        "live": "LIVE",
        "upcoming": "即將開始",
        "waiting": "即將開始",
        "ended": "已結束",
    }.get(item.state, "今日")
    channel_name = item.channel_title or "頻道資訊待補"
    accent_style = _channel_style(item)
    return f"""
<section class="section highlight-section">
  <div class="section-head"><div><h2>今日重點</h2><p>從今天已取得的直播資料自動挑選高訊號事件。</p></div></div>
  <a class="home-highlight" href="{escape(href, quote=True)}"{accent_style}>
    <div class="highlight-thumb"><img src="{thumb}" alt="" loading="lazy"><span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={escape(item.video_id, quote=True)}">YouTube ↗</span></div>
    <div class="highlight-copy">
      <div class="highlight-badges"><span class="highlight-type">{escape(label)}</span><span class="highlight-state{" is-live" if item.state == "live" else ""}">{escape(state_label)}</span>{f'<span class="highlight-type">{len(collab.video_ids)} POV</span>' if collab is not None and len(collab.video_ids) > 1 else ''}</div>
      <h3>{escape(item.title)}</h3>
      <p class="highlight-channel">{escape(channel_name)} · {escape(item.start_label)}</p>
      <span class="highlight-cta">前往觀看 →</span>
    </div>
  </a>
</section>
"""


def _operational_day(value: datetime) -> date:
    local = value.astimezone(TAIPEI)
    return (
        local.date() - timedelta(days=1)
        if local.hour < TODAY_ROLLOVER_HOUR
        else local.date()
    )


def _display_state(
    video: YoutubeVideo | None,
    *,
    now: datetime,
    last_attempt: datetime | None = None,
) -> str:
    """Classify lifecycle using only fresh authoritative observations.

    The 06:00 operational rollover controls which discovery candidates remain
    visible overnight; it must never extend the authority of an old LIVE
    observation. Once checked_at exceeds the freshness window, the card is
    stale until a newer authoritative verification succeeds.
    """

    if video is None:
        return "unknown"
    if video.actual_end is not None:
        return "ended"
    durable_state = stream_state(video, now=now)
    if durable_state == "non_live":
        return "non_live"
    if video.scheduled_start is not None:
        scheduled = video.scheduled_start.astimezone(TAIPEI)
        if scheduled > now:
            return "upcoming"
    checked = video.checked_at
    if checked is None:
        return "unknown"
    checked_local = checked.astimezone(TAIPEI)
    age = now - checked_local
    if age < timedelta(0) or age > STATUS_FRESHNESS:
        return "stale"
    return durable_state


def _home_stream(
    video_id: str,
    *,
    fallback_title: str,
    video: YoutubeVideo | None,
    state: str,
    fallback_start: str | None = None,
    fallback_start_at: datetime | None = None,
    fallback_channel_title: str = "",
    channel_id: str = "",
    avatar_url: str = "",
    hololive_channel_ids: set[str] | None = None,
) -> HomeStream:
    start = video.preferred_start.astimezone(TAIPEI) if video and video.preferred_start else (fallback_start_at.astimezone(TAIPEI) if fallback_start_at else None)
    return HomeStream(
        video_id=video_id,
        title=(video.title if video and video.title else fallback_title) or video_id,
        channel_title=(video.channel_title if video and video.channel_title else fallback_channel_title),
        start_label=start.strftime("%m/%d %H:%M") if start else (fallback_start or "時間未明"),
        state=state,
        start_at=start,
        source_label=fallback_title or "",
        channel_id=channel_id,
        avatar_url=avatar_url,
        group=_stream_group(
            (video.channel_title if video and video.channel_title else fallback_channel_title),
            fallback_title,
            channel_id=channel_id,
            hololive_channel_ids=hololive_channel_ids,
        ),
    )


def load_home_streams(
    *,
    now: datetime | None = None,
    runtime_root: str | Path | None = None,
) -> tuple[list[HomeStream], list[HomeStream], list[HomeStream], list[HomeStream]]:
    """Read today's persisted PTT/channel evidence without external refreshes."""

    current = now or datetime.now(TAIPEI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI)
    source_days = _today_source_days(current)
    snapshot_day = _snapshot_day(current)
    root = Path(runtime_root).expanduser().resolve() if runtime_root is not None else client_runtime_root()
    hololive_channel_ids = _load_hololive_channel_ids(root)

    ptt_cache = LiveDiscoveryCache(root / ".ptt_stream_discovery_cache.json")
    push_store = ChannelPushStore(root / ".channel_push_discovery.json")
    reconcile_store = ChannelPushStore(root / ".channel_feed_reconcile.json")
    status_snapshot_path = root / ".today_stream_status.json"

    catalog_rows = {}
    try:
        catalog_rows = {
            row.video_id: row
            for row in load_client_catalog_streams(root, now=current)
        }
    except (OSError, ValueError, TypeError, sqlite3.Error):
        catalog_rows = {}

    cards = ()
    for source_day in source_days:
        try:
            cards = merge_cards(
                cards,
                build_discovery_cards(ptt_cache, source_day.isoformat()),
            )
        except (OSError, ValueError, TypeError, KeyError):
            continue

    statuses: dict[str, YoutubeVideo] = {}
    for store in (push_store, reconcile_store):
        for source_day in source_days:
            try:
                cards = merge_cards(cards, cards_for_day(store, source_day))
                statuses.update(statuses_for_day(store, source_day))
            except (OSError, ValueError, TypeError, KeyError):
                continue

    snapshot_attempts: dict[str, datetime] = {}
    try:
        snapshot = load_status_snapshot(status_snapshot_path, day=snapshot_day.isoformat())
        if isinstance(snapshot, tuple):
            snapshot_statuses, snapshot_attempts = snapshot
        else:
            snapshot_statuses = snapshot
        statuses.update(snapshot_statuses)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass

    # Client Today keeps HOLOSTARS available for the UI filter; only Shorts
    # remain excluded from this stream-card surface.
    visible_cards = []
    for card in cards:
        video = statuses.get(card.video_id)
        reason = hidden_reason(
            card,
            title=video.title if video else "",
            channel_title=video.channel_title if video else "",
        )
        if reason == "short":
            continue
        visible_cards.append(card)
    cards = tuple(visible_cards)

    catalog_metadata = {}
    try:
        catalog_metadata = load_client_catalog_metadata(
            root, {card.video_id for card in cards}
        )
    except (OSError, ValueError, TypeError, sqlite3.Error):
        catalog_metadata = {}

    live: list[HomeStream] = []
    upcoming: list[HomeStream] = []
    ended: list[HomeStream] = []
    unknown: list[HomeStream] = []

    for card in cards:
        video = statuses.get(card.video_id)
        state = _display_state(
            video,
            now=current,
            last_attempt=snapshot_attempts.get(card.video_id),
        )
        catalog = catalog_rows.get(card.video_id)
        metadata = catalog_metadata.get(card.video_id) or catalog
        if catalog is not None and state in {"unknown", "stale"}:
            # Catalog may rescue missing/old snapshot state only when it is not
            # older than a later failed verification attempt.  Otherwise a
            # previously-positive LIVE row can be resurrected after YouTube has
            # stopped returning that video, which is exactly the unavailable
            # phantom-LIVE failure seen on the Today page.
            last_attempt = snapshot_attempts.get(card.video_id)
            catalog_is_newer_than_attempt = bool(
                last_attempt is None
                or (
                    catalog.last_checked_at is not None
                    and catalog.last_checked_at.astimezone(timezone.utc)
                    >= last_attempt.astimezone(timezone.utc)
                )
            )
            if (
                catalog.lifecycle_state in {"live", "upcoming", "ended"}
                and catalog_is_newer_than_attempt
            ):
                state = catalog.lifecycle_state
        item = _home_stream(
            card.video_id,
            fallback_title=card.label,
            video=video,
            state=state,
            fallback_start=card.ptt_start_label,
            fallback_start_at=(
                (catalog.scheduled_start if catalog else None)
                or (metadata.scheduled_start if metadata else None)
            ),
            fallback_channel_title=(metadata.channel_name if metadata else ""),
            channel_id=(metadata.channel_id if metadata else ""),
            avatar_url=(metadata.avatar_url if metadata else ""),
            hololive_channel_ids=hololive_channel_ids,
        )
        if state == "live":
            live.append(item)
        elif state in {"waiting", "upcoming"}:
            upcoming.append(item)
        elif state == "ended":
            ended.append(item)
        elif state != "non_live":
            unknown.append(item)

    seen_ids = {
        item.video_id
        for group in (live, upcoming, ended, unknown)
        for item in group
    }
    for video_id, catalog in catalog_rows.items():
        if video_id in seen_ids:
            continue
        reference = catalog.actual_start or catalog.scheduled_start or catalog.actual_end
        start_label = reference.astimezone(TAIPEI).strftime("%m/%d %H:%M") if reference else "時間未明"
        item = HomeStream(
            video_id=video_id,
            title=catalog.title or video_id,
            channel_title=catalog.channel_name,
            start_label=start_label,
            start_at=reference.astimezone(TAIPEI) if reference else None,
            state=catalog.lifecycle_state,
            channel_id=catalog.channel_id,
            avatar_url=catalog.avatar_url,
            group=_stream_group(
                catalog.channel_name,
                catalog.title,
                channel_id=catalog.channel_id,
                hololive_channel_ids=hololive_channel_ids,
            ),
        )
        if catalog.lifecycle_state == "live":
            live.append(item)
        elif catalog.lifecycle_state == "upcoming":
            upcoming.append(item)
        elif catalog.lifecycle_state == "ended":
            ended.append(item)

    def sort_key(item: HomeStream) -> tuple[str, str]:
        return item.start_label, item.video_id

    live.sort(key=sort_key)
    upcoming.sort(key=upcoming_sort_key)
    # Prefer verified actual end timestamps. Other records retain a stable
    # fallback, but should not outrank records with confirmed end evidence.
    ended.sort(
        key=lambda item: (
            catalog_rows.get(item.video_id) is not None
            and catalog_rows[item.video_id].actual_end is not None,
            (catalog_rows[item.video_id].actual_end.astimezone(TAIPEI)
             if catalog_rows.get(item.video_id) is not None
             and catalog_rows[item.video_id].actual_end is not None
             else item.start_at or datetime.min.replace(tzinfo=TAIPEI)),
            item.video_id,
        ),
        reverse=True,
    )
    unknown.sort(key=sort_key)
    return live, upcoming, ended, unknown


def upcoming_sort_key(item: HomeStream) -> tuple[bool, datetime, str]:
    """Order planned streams by absolute start time, with unknown dates last."""
    return (item.start_at is None, item.start_at or datetime.max.replace(tzinfo=TAIPEI), item.video_id)


def _collab_href(candidate: CollabCandidate) -> str:
    query = [("collab", candidate.event_key)]
    query.extend(("stream", video_id) for video_id in candidate.video_ids)
    return "/collab/session?" + urlencode(query)


def _stream_card(item: HomeStream, collab_candidate: CollabCandidate | None = None) -> str:
    href = "/custom-view/session?" + urlencode(
        [("stream", item.video_id), ("layout", "auto"), ("primary", "0"), ("audio", "0")]
    )
    label = {
        "live": ("LIVE", "live"),
        "waiting": ("等待中", "upcoming"),
        "upcoming": ("即將開始", "upcoming"),
        "ended": ("已結束", "ended"),
        "unknown": ("狀態待更新", ""),
        "stale": ("狀態待更新", ""),
    }.get(item.state, ("", ""))
    badge = f'<span class="thumb-badge {label[1]}">{escape(label[0])}</span>' if label[0] else ""
    thumb = f"https://i.ytimg.com/vi/{escape(item.video_id)}/mqdefault.jpg"
    channel_name = item.channel_title or "頻道資訊待補"
    avatar_text = next((char for char in channel_name if char.isalnum()), "H").upper()
    avatar_inner = (
        f'<img class="channel-avatar-img" src="{escape(item.avatar_url, quote=True)}" alt="" loading="lazy">'
        if item.avatar_url
        else f'<span class="channel-avatar-fallback" aria-hidden="true">{escape(avatar_text)}</span>'
    )
    avatar = f'<span class="channel-avatar-ring">{avatar_inner}</span>'
    accent_style = _channel_style(item)
    # Multi-select was originally limited to LIVE cards only:
    #   if item.state == "live"
    # Keep that product gate documented here in case we want to restore it,
    # but for now allow explicit multi-view assembly from playable/scheduled
    # cards as well. Unknown/stale remains single-open because lifecycle
    # evidence is not reliable enough to assemble a session from the home page.
    selectable_states = {"live", "waiting", "upcoming", "ended"}
    selectable = (
        f' data-multiview-id="{escape(item.video_id, quote=True)}" aria-selected="false"'
        if item.state in selectable_states
        else ""
    )
    collab_entry = ""
    if collab_candidate is not None:
        collab_url = escape(_collab_href(collab_candidate), quote=True)
        collab_entry = (
            f'<span class="stream-collab-entry" role="link" tabindex="0" '
            f'data-collab-href="{collab_url}" aria-label="進入多人連動" title="進入多人連動"><span class="collab-glyph" aria-hidden="true">👥</span><span class="collab-entry-label">多人</span></span>'
        )
    return f"""<a id="stream-{escape(item.video_id, quote=True)}" class="client-card stream-card" data-group="{escape(item.group, quote=True)}" href="{escape(href, quote=True)}"{accent_style}{selectable}>
<div class="card-thumb">
  <img src="{thumb}" alt="" loading="lazy">
  <span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={escape(item.video_id, quote=True)}">YouTube ↗</span>
  <div class="thumb-overlay">{badge}<span class="thumb-time">{escape(item.start_label)}</span></div>
</div>
<div class="yt-meta">
  {avatar}
  <div class="yt-copy">
    <h3 class="stream-title">{escape(item.title)}</h3>
    <div class="channel-name">{escape(channel_name)}</div>
  </div>
</div>{collab_entry}</a>"""


def _live_channel_rail(items: list[HomeStream]) -> str:
    if not items:
        return ""
    seen: set[str] = set()
    chips: list[str] = []
    for item in items:
        key = item.channel_id or item.channel_title or item.video_id
        if key in seen:
            continue
        seen.add(key)
        name = item.channel_title or "頻道資訊待補"
        accent_style = _channel_style(item)
        avatar_text = next((char for char in name if char.isalnum()), "H").upper()
        avatar = (
            f'<img src="{escape(item.avatar_url, quote=True)}" alt="" loading="lazy">'
            if item.avatar_url
            else f'<span aria-hidden="true">{escape(avatar_text)}</span>'
        )
        chips.append(
            f'<a class="live-channel-rail-item" data-group="{escape(item.group, quote=True)}" '
            f'href="/#stream-{escape(item.video_id, quote=True)}" data-live-video-id="{escape(item.video_id, quote=True)}" data-channel-id="{escape(item.channel_id or "", quote=True)}"{accent_style}>'
            f'<span class="live-channel-avatar">{avatar}<i></i></span>'
            f'<strong>{escape(name)}</strong></a>'
        )
    return (
        '<aside class="live-channel-rail" aria-label="目前直播頻道">'
        '<span class="live-channel-label">直播頻道</span>'
        + "".join(chips)
        + '</aside>'
    )


def _stream_section(title: str, items: list[HomeStream], subtitle: str = "", *, collab_by_video: dict[str, CollabCandidate] | None = None) -> str:
    if not items:
        return ""
    collab_by_video = collab_by_video or {}
    cards = "".join(_stream_card(item, collab_by_video.get(item.video_id)) for item in items)
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    return (
        '<section class="section">'
        f'<div class="section-head"><div><h2>{escape(title)}</h2>{subtitle_html}</div></div>'
        f'<div class="client-grid">{cards}</div></section>'
    )


def build_home_fragment(
    live: list[HomeStream],
    upcoming: list[HomeStream],
    ended: list[HomeStream],
    unknown: list[HomeStream] | None = None,
    *,
    today_label: str,
) -> str:
    """Render only the replaceable Today content; no shell or external refresh."""

    unknown = list(unknown or [])
    collab_candidates = detect_collab_candidates([*live, *upcoming, *ended])
    collab_by_video = {
        video_id: candidate
        for candidate in collab_candidates
        for video_id in candidate.video_ids
    }
    # Recent focus is intentionally forward-looking: LIVE/upcoming only.
    # Detected multi-POV events consume one slide rather than one slide per POV.
    highlights = select_home_highlights(
        live, upcoming, limit=6, collab_by_video=collab_by_video
    )
    announcement_html = _home_announcement_strip(highlights)
    highlight_html = _home_highlight_carousel(highlights, collab_by_video)
    empty = ""
    if not live and not upcoming and not ended and not unknown:
        empty = (
            '<p class="empty-note">目前 runtime root 沒有今天的 PTT／頻道 discovery 資料；'
            "首頁不會為了補畫面主動查外部 API。</p>"
        )
    return f"""
<div class="page-head">
  <div><h1>今日直播</h1></div>
</div>
<div class="stream-filter" role="group" aria-label="直播群組">
  <button class="stream-filter-button active" type="button" data-filter="hololive">Hololive</button>
  <button class="stream-filter-button" type="button" data-filter="holostars">HOLOSTARS</button>
  <button class="stream-filter-button" type="button" data-filter="mekpark">mekPark</button>
  <button class="stream-filter-button" type="button" data-filter="all">全部</button>
</div>
{announcement_html}
{highlight_html}
{_stream_section("現在直播中", live, "目前可直接觀看的直播。", collab_by_video=collab_by_video)}
{_stream_section("即將開始", upcoming, "已排程、尚未開始的直播。", collab_by_video=collab_by_video)}
{_stream_section("狀態待更新", unknown, "已找到直播，但目前沒有足夠新的 lifecycle 證據。")}
<section class="section">
  <div class="section-head"><div><h2>觀看方式</h2></div></div>
  <div class="feature-row">
    <a class="feature-card" href="/watchalong"><div><span class="eyebrow">WATCHALONG</span><strong>同時視聽</strong></div><span>Hololive 保持主時間軸，片源跟隨觀看。</span></a>
    <a class="feature-card" href="/custom-view"><div><span class="eyebrow">CUSTOM</span><strong>自訂觀看</strong></div><span>自由加入直播、排列畫面並指定主要聲音。</span></a>
    <a class="feature-card" href="/ptt-today"><div><span class="eyebrow">PTT</span><strong>PTT 今日專串</strong></div><span>只留下今天的 PTT 推文時間軸。</span></a>
  </div>
</section>
{_stream_section("已結束", ended, "今天已完成的直播存檔。", collab_by_video=collab_by_video)}
{empty}
"""


HOME_REFRESH_SCRIPT = r"""
const homeDynamic=document.getElementById('homeDynamic');
let homeRefreshInFlight=false;
let activeStreamFilter=window.holoviewerLiveFilter?.read()||'hololive';
const selectedStreamIds=new Set();
const multiBar=document.getElementById('multiSelectBar');
function syncMultiSelection(){
  if(!homeDynamic)return;
  const cards=[...homeDynamic.querySelectorAll('.stream-card[data-multiview-id]')];
  const available=new Set(cards.map(card=>card.dataset.multiviewId));
  for(const id of selectedStreamIds){if(!available.has(id))selectedStreamIds.delete(id);}
  cards.forEach(card=>{const chosen=selectedStreamIds.has(card.dataset.multiviewId);card.classList.toggle('multi-selected',chosen);card.setAttribute('aria-selected',String(chosen));});
  if(multiBar)multiBar.hidden=selectedStreamIds.size===0;
  const count=document.getElementById('multiSelectCount');
  if(count)count.textContent='已選 '+selectedStreamIds.size+' 個影片';
  const watch=document.getElementById('multiWatch');
  if(watch)watch.textContent=selectedStreamIds.size>1?'開始多視角觀看':'觀看選取影片';
}
homeDynamic?.addEventListener('click',event=>{
  const collabEntry=event.target.closest('[data-collab-href]');
  if(collabEntry){
    event.preventDefault();event.stopPropagation();
    location.href=collabEntry.dataset.collabHref;return;
  }
  const card=event.target.closest('.stream-card[data-multiview-id]');
  if(!card)return;
  event.preventDefault();
  const id=card.dataset.multiviewId;
  if(selectedStreamIds.has(id))selectedStreamIds.delete(id);else selectedStreamIds.add(id);
  syncMultiSelection();
});
document.getElementById('multiClear')?.addEventListener('click',()=>{selectedStreamIds.clear();syncMultiSelection();});
document.getElementById('multiWatch')?.addEventListener('click',()=>{
  if(!selectedStreamIds.size)return;
  const query=new URLSearchParams();
  selectedStreamIds.forEach(id=>query.append('stream',id));
  query.set('layout','auto');query.set('primary','0');query.set('audio','0');
  location.href='/custom-view/session?'+query.toString();
});


function applyStreamFilter(){
  if(!homeDynamic)return;
  const filterables=[...homeDynamic.querySelectorAll('.stream-card')];
  filterables.forEach(item=>{
    const group=item.dataset.group||'other';
    item.hidden=activeStreamFilter!=='all'&&group!==activeStreamFilter;
  });
  window.holoviewerLiveFilter?.sync(activeStreamFilter);
  homeDynamic.querySelectorAll('.stream-filter-button').forEach(button=>{
    button.classList.toggle('active',button.dataset.filter===activeStreamFilter);
  });
}

homeDynamic?.addEventListener('click',(event)=>{
  const button=event.target.closest('.stream-filter-button');
  if(!button)return;
  activeStreamFilter=button.dataset.filter||'hololive';
  window.holoviewerLiveFilter?.set(activeStreamFilter);
  applyStreamFilter();
});
function showHighlightSlide(carousel,index,direction=1){
  const slides=[...carousel.querySelectorAll('.highlight-slide')];
  if(!slides.length||carousel.dataset.sliding==='true')return;
  const active=(index+slides.length)%slides.length;
  const previous=Number(carousel.dataset.activeSlide||0);
  if(previous===active)return;
  const activate=()=>{
    slides.forEach((slide,i)=>{slide.hidden=i!==active;});
    carousel.querySelectorAll('.highlight-dot').forEach((dot,i)=>dot.classList.toggle('active',i===active));
    carousel.dataset.activeSlide=String(active);
  };
  if(window.matchMedia('(prefers-reduced-motion: reduce)').matches||!slides[previous]?.animate){
    activate();return;
  }
  carousel.dataset.sliding='true';
  const sign=direction<0?-1:1;
  const outgoing=slides[previous].animate(
    [{opacity:1,transform:'translateX(0)'},{opacity:0,transform:'translateX('+(-sign*8)+'%)'}],
    {duration:250,easing:'ease-in',fill:'forwards'}
  );
  outgoing.finished.then(()=>{
    outgoing.cancel();activate();
    const incoming=slides[active].animate(
      [{opacity:0,transform:'translateX('+(sign*8)+'%)'},{opacity:1,transform:'translateX(0)'}],
      {duration:380,easing:'ease-out'}
    );
    return incoming.finished;
  }).catch(()=>{}).finally(()=>{carousel.dataset.sliding='false';});
}
homeDynamic?.addEventListener('click',(event)=>{
  const carousel=event.target.closest('.highlight-carousel');
  if(!carousel)return;
  const dot=event.target.closest('[data-slide-to]');
  if(dot){const target=Number(dot.dataset.slideTo);showHighlightSlide(carousel,target,target<Number(carousel.dataset.activeSlide||0)?-1:1);return;}
  const current=Number(carousel.dataset.activeSlide||0);
  if(event.target.closest('.highlight-prev'))showHighlightSlide(carousel,current-1,-1);
  if(event.target.closest('.highlight-next'))showHighlightSlide(carousel,current+1);
});
const highlightAutoTimer=setInterval(()=>{
  if(document.hidden||!homeDynamic)return;
  const carousel=homeDynamic.querySelector('.highlight-carousel');
  if(!carousel||carousel.matches(':hover')||carousel.matches(':focus-within'))return;
  const slides=carousel.querySelectorAll('.highlight-slide');
  if(slides.length<2)return;
  showHighlightSlide(carousel,Number(carousel.dataset.activeSlide||0)+1);
},10000);
// Hold each reminder before sliding to the next; DOM survives the 30s home refresh.
// Display precisely one complete notice at rest; the next notice never peeks in.
let announcementIndex=0;
let announcementTimer=null;
let announcementTransitionTimer=null;
function scheduleAnnouncement(){
  clearTimeout(announcementTimer);
  const panel=homeDynamic?.querySelector('.announcement-messages');
  const entries=[...panel?.querySelectorAll('.announcement-entry')||[]];
  if(entries.length<2)return;
  const active=entries[announcementIndex%entries.length];
  // Long Japanese titles need more reading time than short notices.
  const chars=active?.textContent?.length||0;
  const dwell=Math.min(10000,Math.max(5000,chars*100));
  announcementTimer=setTimeout(()=>{
    if(document.hidden||panel.matches(':hover')||panel.matches(':focus-within')){
      scheduleAnnouncement();return;
    }
    const next=(announcementIndex+1)%entries.length;
    const current=entries[announcementIndex];
    const incoming=entries[next];
    if(!current||!incoming){announcementIndex=0;scheduleAnnouncement();return;}
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      current.hidden=true;incoming.hidden=false;announcementIndex=next;scheduleAnnouncement();return;
    }
    current.classList.add('notice-exit');
    announcementTransitionTimer=setTimeout(()=>{
      current.hidden=true;current.classList.remove('notice-exit');
      incoming.hidden=false;incoming.classList.add('notice-enter');
      requestAnimationFrame(()=>requestAnimationFrame(()=>incoming.classList.remove('notice-enter')));
      announcementIndex=next;
      scheduleAnnouncement();
    },750);
  },dwell);
}
function restoreAnnouncement(){
  clearTimeout(announcementTimer);
  clearTimeout(announcementTransitionTimer);
  const entries=[...homeDynamic?.querySelectorAll('.announcement-entry')||[]];
  if(entries.length){
    announcementIndex%=entries.length;
    entries.forEach((entry,i)=>{entry.hidden=i!==announcementIndex;entry.classList.remove('notice-exit','notice-enter');});
  }else announcementIndex=0;
  scheduleAnnouncement();
}
restoreAnnouncement();
function formatEnglishHomeDate(label){
  const parts=/^([0-9]{4})[/]([0-9]{2})[/]([0-9]{2})$/.exec(label);
  if(!parts)return label;
  const d=new Date(Date.UTC(Number(parts[1]),Number(parts[2])-1,Number(parts[3])));
  const day=['SUN','MON','TUE','WED','THU','FRI','SAT'][d.getUTCDay()];
  const month=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][d.getUTCMonth()];
  return day+' · '+month+' '+String(d.getUTCDate()).padStart(2,'0')+', '+parts[1];
}
async function refreshHome(){
  if(!homeDynamic||document.hidden||homeRefreshInFlight)return;
  homeRefreshInFlight=true;
  try{
    const response=await fetch('/api/home',{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!response.ok)return;
    const payload=await response.json();
    if(typeof payload.html==='string'){homeDynamic.innerHTML=payload.html;applyStreamFilter();syncMultiSelection();restoreAnnouncement();}
    const status=document.querySelector('.top-status');
    if(status&&typeof payload.today_label==='string')status.textContent=formatEnglishHomeDate(payload.today_label);
  }catch(_error){
    // Keep the last good local render; the next visible interval retries.
  }finally{
    homeRefreshInFlight=false;
  }
}
const homeRefreshTimer=setInterval(refreshHome,30000);
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden)refreshHome();
});
window.addEventListener('pagehide',()=>{clearInterval(homeRefreshTimer);clearInterval(highlightAutoTimer);clearTimeout(announcementTimer);clearTimeout(announcementTransitionTimer);},{once:true});
applyStreamFilter();
syncMultiSelection();
"""


def _english_home_date(today_label: str) -> str:
    """Presentation-only date; preserve the canonical YYYY/MM/DD refresh label."""
    try:
        return datetime.strptime(today_label, "%Y/%m/%d").strftime("%a · %b %d, %Y").upper()
    except ValueError:
        return today_label


def build_home_html(
    live: list[HomeStream],
    upcoming: list[HomeStream],
    ended: list[HomeStream],
    unknown: list[HomeStream] | None = None,
    *,
    today_label: str,
    history_content: str | None = None,
) -> str:
    content = (
        '<div id="homeDynamic">'
        + build_home_fragment(live, upcoming, ended, unknown, today_label=today_label)
        + "</div>"
        + '<div class="multi-select-bar" id="multiSelectBar" hidden aria-live="polite">'
          '<span id="multiSelectCount">已選 0 個直播</span>'
          '<button type="button" id="multiClear">清除</button>'
          '<button type="button" id="multiWatch">開始觀看</button>'
          '</div>'
    )
    if history_content is not None:
        content = (
            history_content +
            '<div class="multi-select-bar" id="multiSelectBar" hidden aria-live="polite">'
            '<span id="multiSelectCount">已選 0 個影片</span>'
            '<button type="button" id="multiClear">清除</button>'
            '<button type="button" id="multiWatch">開始觀看</button></div>'
        )
    home_css = r"""
body.home-wide .client-main{max-width:1580px;padding-top:24px}
/* One FUWAMOCO card receives an ordered dual-color community penlight accent. */
[data-support-mode="dual_color"] .channel-avatar-ring,[data-support-mode="dual_color"] .live-channel-avatar{background:var(--member-accent-dual)!important;border-color:transparent!important;padding:3px}
[data-support-mode="dual_color"] .channel-avatar-img,[data-support-mode="dual_color"] .live-channel-avatar img{background:#fff;border-radius:50%}
body.home-wide .page-head{margin-bottom:10px}
body.home-wide .page-head h1{font-size:30px;margin-bottom:0}
body.home-wide .section{margin:18px 0 24px}
body.home-wide .section-head{margin-bottom:9px}
.stream-card[data-multiview-id]{cursor:pointer}
.stream-card[data-multiview-id].multi-selected{border:2px solid #2d83a0!important;background:#edf8fb!important;box-shadow:0 0 0 3px rgba(45,131,160,.18)!important;animation:none!important}
.stream-card[data-multiview-id].multi-selected:after{content:"✓ 已選取";position:absolute;right:16px;top:16px;background:#116683;color:#fff;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:800;z-index:4}
.multi-select-bar[hidden]{display:none!important}
.multi-select-bar{position:fixed;z-index:50;bottom:24px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:12px;padding:12px 16px;background:#17191d;color:white;border-radius:16px;box-shadow:0 10px 35px rgba(0,0,0,.27);max-width:calc(100vw - 24px)}
.multi-select-bar button{border:1px solid #555;border-radius:9px;padding:9px 13px;color:white;background:#34393f;cursor:pointer;white-space:nowrap}
.multi-select-bar #multiWatch{background:#fff;color:#17191d;font-weight:800}
@media(max-width:600px){.multi-select-bar{bottom:8px;gap:7px;padding:8px;font-size:12px}.multi-select-bar button{padding:8px}}

.client-grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:28px 18px}
.stream-card{position:relative;border:1px solid transparent;background:transparent;border-radius:18px;overflow:visible;box-shadow:none;padding:8px;transition:border-color .14s ease,box-shadow .14s ease}
.stream-collab-entry{position:absolute;right:8px;bottom:8px;z-index:4;min-width:54px;height:42px;padding:0 9px;border-radius:13px;display:flex;align-items:center;justify-content:center;gap:4px;background:#fff;border:1px solid var(--line);box-shadow:0 4px 12px rgba(52,44,36,.18);font-weight:900;color:#356f89;cursor:pointer}\n.stream-collab-entry .collab-glyph{font-size:25px;line-height:1}.stream-collab-entry .collab-entry-label{font-size:10px;line-height:1;letter-spacing:.02em}\n.stream-collab-entry:hover,.stream-collab-entry:focus-visible{background:var(--accent-soft);outline:2px solid #4f7f93;outline-offset:1px}\n.stream-card:hover,.stream-card:focus-visible{
  transform:none;
  border-color:color-mix(in srgb,var(--member-accent,#7aa8bb) 72%,white);
  background:#fff;
  box-shadow:
    0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 34%,transparent),
    0 0 14px color-mix(in srgb,var(--member-accent,#7aa8bb) 30%,transparent),
    0 9px 22px rgba(52,44,36,.07);
  animation:memberGlow 1.8s ease-in-out infinite alternate;
  outline:none
}
@keyframes memberGlow{
  from{box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 28%,transparent),0 0 8px color-mix(in srgb,var(--member-accent,#7aa8bb) 20%,transparent),0 9px 22px rgba(52,44,36,.06)}
  to{box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 48%,transparent),0 0 17px color-mix(in srgb,var(--member-accent,#7aa8bb) 38%,transparent),0 9px 22px rgba(52,44,36,.07)}
}
.stream-card[hidden]{display:none!important}
.card-thumb{border-radius:16px;overflow:hidden;box-shadow:0 1px 0 rgba(52,44,36,.04)}
.thumb-overlay{position:absolute;left:8px;right:8px;bottom:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;pointer-events:none}
.thumb-badge,.thumb-time{display:inline-flex;align-items:center;min-height:22px;padding:0 7px;border-radius:6px;font-size:10px;font-weight:800;backdrop-filter:blur(6px)}
.thumb-badge{background:rgba(30,30,30,.78);color:#fff}
.thumb-badge.live{background:#d93045}.thumb-badge.upcoming{background:#8e6500}.thumb-badge.ended{background:rgba(65,65,65,.78)}
.thumb-time{margin-left:auto;background:rgba(20,20,20,.74);color:#fff}
.yt-meta{display:grid;grid-template-columns:40px minmax(0,1fr);gap:12px;padding:12px 2px 0}
.channel-avatar-ring{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;padding:2px;background:white;border:2px solid var(--member-accent,#9ab8c4);box-shadow:0 0 0 1px rgba(48,43,51,.25),0 0 0 3px color-mix(in srgb,var(--member-accent,#9ab8c4) 24%,transparent)}
.channel-avatar-img,.channel-avatar-fallback{width:100%;height:100%;border-radius:50%}
.channel-avatar-img{display:block;object-fit:cover;background:var(--surface-2)}
.channel-avatar-fallback{display:grid;place-items:center;background:color-mix(in srgb,var(--member-accent,#6faec9) 12%,white);color:var(--member-accent,#4f7f93);font-size:12px;font-weight:800}
.yt-copy{min-width:0}.stream-title{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;min-height:42px;max-height:42px;margin:0 0 5px!important;font-size:15px!important;line-height:1.45!important}
.channel-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:color-mix(in srgb,var(--member-accent,var(--muted)) 62%,#25232a);font-size:12.5px;font-weight:750}
@media(max-width:1040px){.client-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:26px 18px}}
@media(max-width:620px){.client-grid{grid-template-columns:1fr;gap:24px}.yt-meta{grid-template-columns:40px minmax(0,1fr)}}
.stream-filter{display:flex;align-items:center;gap:8px;margin:2px 0 6px}
.stream-filter-button{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:999px;padding:8px 14px;font-size:12px;font-weight:750;cursor:pointer}
.stream-filter-button:hover{background:var(--surface-2)}
.stream-filter-button.active{background:var(--text);border-color:var(--text);color:white}
.section:last-of-type .stream-card{opacity:.9}
.home-announcements{display:flex;align-items:center;gap:14px;padding:10px 16px;border:1px solid var(--line);border-radius:12px;background:var(--surface);margin:7px 0 12px;font-size:13px;overflow:hidden}.announcement-heading{font-weight:800;white-space:nowrap;color:var(--accent)}.announcement-messages{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.announcement-messages a{color:var(--text);text-decoration:none}.announcement-messages a:hover{text-decoration:underline}.highlight-slide[hidden]{display:none!important}.highlight-controls{display:flex;justify-content:center;align-items:center;gap:16px;padding:12px}.highlight-controls button{cursor:pointer;border:1px solid var(--line);background:var(--surface);border-radius:99px;min-width:34px;min-height:30px}.highlight-dots{display:flex;gap:7px}.highlight-dots .highlight-dot{min-width:9px;min-height:9px;width:9px;height:9px;padding:0;background:var(--line);border:0}.highlight-dots .highlight-dot.active{background:var(--text)}

.announcement-messages{flex:1;min-width:0}
.announcement-slide[hidden]{display:none!important}
.announcement-slide{white-space:normal;overflow-wrap:anywhere;line-height:1.5}
.announcement-slide a{display:block}
.announcement-controls{margin-left:auto;display:flex;align-items:center;gap:5px;flex:0 0 auto}
.announcement-controls button{cursor:pointer;border:1px solid #dca848;border-radius:7px;background:#fff7e7;color:#68420f;font-size:19px;line-height:1;width:30px;height:30px}
.announcement-count{font-size:11px;color:#775e32;min-width:35px;text-align:center;font-variant-numeric:tabular-nums}

.announcement-messages{flex:1;min-width:0;overflow:hidden!important;white-space:nowrap!important}
.announcement-track{position:relative;display:block;width:100%;min-width:0;overflow:hidden}
.announcement-entry{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:opacity .75s ease,transform .75s ease;opacity:1;transform:translateX(0)}
.announcement-entry[hidden]{display:none!important}
.announcement-entry.notice-exit{opacity:0;transform:translateX(-28px)}
.announcement-entry.notice-enter{opacity:0;transform:translateX(28px)}
.announcement-entry a{display:block;overflow:hidden;text-overflow:ellipsis}
@media(prefers-reduced-motion:reduce){.announcement-entry{transition:none}}
/* 4174 homepage acceptance: notice contrast, integrated hero controls, legible time. */
.home-announcements{background:#fff1d8!important;border:1px solid #dca848!important;border-left:5px solid #be7513!important;box-shadow:0 3px 12px rgba(130,84,8,.10);padding:14px 18px!important;gap:16px!important}
.announcement-heading{display:inline-flex;align-items:center;flex:0 0 auto;color:#6a3a00!important;background:#ffd989;padding:7px 12px;border-radius:8px;font-size:13px;font-weight:900}
.announcement-messages{font-size:14px;font-weight:650;line-height:1.65;color:#49300b}
.announcement-messages a{color:#4b2e09!important}
.announcement-messages strong{color:#9b3318;background:#fff;border-radius:6px;padding:4px 7px;margin-right:4px}
.highlight-carousel{position:relative;padding-bottom:12px}
.highlight-slide{min-width:0}
.highlight-controls{position:absolute;inset:0 0 12px;display:flex!important;align-items:center;justify-content:space-between!important;padding:0 14px!important;pointer-events:none}
.highlight-controls>.highlight-prev,.highlight-controls>.highlight-next{pointer-events:auto;z-index:3;display:grid;place-items:center;width:44px;height:44px;min-width:44px;min-height:44px;border-radius:50%!important;background:rgba(24,26,31,.83)!important;color:white!important;border:1px solid rgba(255,255,255,.5)!important;font-size:32px;line-height:1;box-shadow:0 2px 12px rgba(0,0,0,.28)}
.highlight-controls>.highlight-prev:hover,.highlight-controls>.highlight-next:hover{background:#101116!important;transform:scale(1.07)}
.highlight-dots{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);display:flex;gap:8px;pointer-events:auto;background:rgba(20,20,20,.58);padding:9px 12px;border-radius:99px}
.highlight-dots .highlight-dot{width:10px;height:10px;min-width:10px;min-height:10px;background:#ddd}
.highlight-dots .highlight-dot.active{background:#ffc968}
.thumb-time{padding:5px 10px!important;min-height:30px!important;font-size:13px!important;font-weight:900!important;letter-spacing:.02em;background:rgba(12,18,25,.94)!important;color:#fff!important;border:1px solid rgba(255,255,255,.65)!important;box-shadow:0 1px 7px rgba(0,0,0,.4)}
@media(max-width:620px){.home-announcements{align-items:flex-start;flex-direction:column;gap:8px!important}.announcement-messages{white-space:normal}.highlight-controls{padding:0 6px!important}.highlight-controls>.highlight-prev,.highlight-controls>.highlight-next{width:36px;height:36px;min-width:36px;min-height:36px;font-size:26px}.thumb-time{font-size:12px!important}}
.home-highlight{display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr);height:clamp(165px,22vh,230px);min-height:0;border:1px solid color-mix(in srgb,var(--member-accent,#9ab8c4) 34%,var(--line));border-radius:20px;overflow:hidden;background:var(--surface);box-shadow:0 8px 24px rgba(52,44,36,.05);transition:border-color .14s ease,box-shadow .14s ease}
.home-highlight:hover,.home-highlight:focus-visible{border-color:color-mix(in srgb,var(--member-accent,#7aa8bb) 72%,white);box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 30%,transparent),0 0 16px color-mix(in srgb,var(--member-accent,#7aa8bb) 28%,transparent),0 10px 24px rgba(52,44,36,.07);outline:none}
.highlight-thumb{min-height:0;height:100%;background:#ddd;overflow:hidden}.highlight-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.highlight-copy{padding:10px 20px;min-height:0;display:flex;flex-direction:column;justify-content:center}
.highlight-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:7px}.highlight-type,.highlight-state{display:inline-flex;align-items:center;min-height:25px;padding:0 9px;border-radius:999px;font-size:11px;font-weight:800}
.highlight-type{background:var(--accent-soft);color:#4f7f93}.highlight-state{background:#f2eee8;color:#665f56}.highlight-state.is-live{background:#e6213c;color:#fff;box-shadow:0 0 0 1px rgba(155,12,37,.12)}
.highlight-copy h3{margin:0 0 8px;font-size:clamp(17px,1.6vw,23px);line-height:1.35;letter-spacing:-.02em}.highlight-copy p{margin:0;color:var(--muted);font-size:13px}.highlight-copy .highlight-channel{color:var(--member-accent,var(--muted));font-weight:750}
.highlight-cta{margin-top:12px;font-size:13px;font-weight:800}
@media(max-width:760px){.home-highlight{grid-template-columns:1fr;height:auto}.highlight-thumb{height:auto;min-height:0;aspect-ratio:16/9}.highlight-copy{padding:18px}.highlight-copy h3{font-size:19px}}
/* Clicking a live-channel avatar uses a native #stream-id jump; reserve the sticky header. */
.stream-card[id^="stream-"]{scroll-margin-top:calc(58px + 14px)}
/* Tone down spotlight navigation and remove asymmetric shadow artifacts. */
.home-highlight{box-shadow:none!important}
.home-highlight:hover,.home-highlight:focus-visible{box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#9ab8c4) 25%,transparent)!important}
.highlight-controls>.highlight-prev,.highlight-controls>.highlight-next{background:rgba(24,26,31,.43)!important;border-color:rgba(255,255,255,.3)!important;box-shadow:none!important}
.highlight-controls>.highlight-prev:hover,.highlight-controls>.highlight-next:hover{background:rgba(24,26,31,.68)!important;box-shadow:none!important}
.highlight-dots{bottom:4px!important;background:rgba(57,54,60,.27)!important;box-shadow:none!important}
.highlight-dots .highlight-dot{background:rgba(255,255,255,.58)!important;border-color:transparent!important;box-shadow:none!important}
.highlight-dots .highlight-dot.active{background:rgba(255,255,255,.9)!important}
/* Keep the announcement legible without competing with live thumbnails. */
.home-announcements{background:#fff9ed!important;border-color:#edd9b4!important;border-left-color:#d7ab64!important;box-shadow:none!important;padding:8px 14px!important;gap:12px!important}
.announcement-heading{background:#ffe9ba!important;padding:5px 9px!important}
"""
    return client_document(
        title="歷史直播" if history_content is not None else "今日直播",
        active="history" if history_content is not None else "home",
        content=content,
        extra_css=home_css + """
.history-picker,.history-shortcuts{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}
.history-picker input{min-height:40px;padding:6px 10px;border:1px solid var(--line);border-radius:9px}
.history-shortcuts .subtle-action{min-height:34px;padding:6px 11px}
""",
        extra_script=(HOME_REFRESH_SCRIPT.split("function applyStreamFilter(){", 1)[0]
                      if history_content is not None else HOME_REFRESH_SCRIPT),
        top_status=_english_home_date(today_label),
        body_class="home-wide",
        live_rail_html=("" if history_content is not None else _live_channel_rail(live)),
    )


COLLAB_RECENT_DAYS = 14


@dataclass(frozen=True)
class CollabEventQuery:
    """Stable query contract for a replaceable History 66/catalog provider."""

    since: datetime
    until: datetime


class CollabEventSource:
    """Replaceable read-only source boundary for collab event discovery."""

    def list_streams(
        self, query: CollabEventQuery,
    ) -> tuple[list[HomeStream], list[HomeStream], list[HomeStream]]:
        raise NotImplementedError


class RuntimeCollabEventSource(CollabEventSource):
    """Current 4174 provider. Future catalog/DB adapters can replace this class."""

    def __init__(self, loader=load_home_streams):
        self.loader = loader

    def list_streams(
        self, query: CollabEventQuery,
    ) -> tuple[list[HomeStream], list[HomeStream], list[HomeStream]]:
        # Today's runtime loader is intentionally narrower than the query window.
        # History 66/catalog adapters can honor the full window without UI changes.
        del query
        live, upcoming, ended, _unknown = self.loader()
        return live, upcoming, ended


def load_collab_event_streams(
    source: CollabEventSource | None = None,
    *,
    now: datetime | None = None,
    recent_days: int = COLLAB_RECENT_DAYS,
) -> tuple[list[HomeStream], list[HomeStream], list[HomeStream]]:
    """Load recent collab inputs without exposing DB paths or schemas to UI code."""
    current = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    # Calendar-window semantics: today plus the previous 13 local dates.
    since = (current - timedelta(days=max(1, recent_days) - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    until = current.replace(hour=23, minute=59, second=59, microsecond=999999)
    query = CollabEventQuery(since=since, until=until)
    return (source or RuntimeCollabEventSource()).list_streams(query)


def _collab_event_card(candidate: CollabCandidate, streams_by_id: dict[str, HomeStream]) -> str:
    members = [streams_by_id[video_id] for video_id in candidate.video_ids if video_id in streams_by_id]
    if not members:
        return ""
    members.sort(key=lambda item: (item.start_at or datetime.min.replace(tzinfo=TAIPEI), item.video_id))
    representative = members[0]
    href = escape(_collab_href(candidate), quote=True)
    thumb = f"https://i.ytimg.com/vi/{escape(representative.video_id)}/hqdefault.jpg"
    live_count = sum(item.state == "live" for item in members)
    upcoming_count = sum(item.state in {"upcoming", "waiting"} for item in members)
    ended_count = sum(item.state == "ended" for item in members)
    state = "live" if live_count else ("upcoming" if upcoming_count else "ended")
    state_label = "LIVE" if state == "live" else ("稍後" if state == "upcoming" else "已結束")
    event_at = max((item.start_at for item in members if item.start_at), default=None)
    date_label = event_at.astimezone(TAIPEI).strftime("%Y/%m/%d") if event_at else "日期未明"
    avatars = []
    seen = set()
    for item in members:
        channel = item.channel_id or item.channel_title
        if channel in seen:
            continue
        seen.add(channel)
        name = item.channel_title or "Hololive"
        fallback = next((char for char in name if char.isalnum()), "H").upper()
        inner = (f'<img src="{escape(item.avatar_url, quote=True)}" alt="{escape(name, quote=True)}" loading="lazy">'
                 if item.avatar_url else f'<span>{escape(fallback)}</span>')
        avatars.append(f'<span class="collab-avatar" title="{escape(name, quote=True)}">{inner}</span>')
    title = candidate.label.replace("候選", "").strip(" ·")
    status_bits = []
    if live_count:
        status_bits.append(f"{live_count} 個直播中")
    if upcoming_count:
        status_bits.append(f"{upcoming_count} 個稍後開始")
    if ended_count:
        status_bits.append(f"{ended_count} 個已結束")
    pov_note = f"{len(members)} 個 POV"
    if status_bits:
        pov_note += " · " + " · ".join(status_bits)
    return (
        f'<a class="collab-event-card {state}" href="{href}" data-event-date="{date_label}">'
        f'<div class="collab-event-thumb"><img src="{thumb}" alt="" loading="lazy">'
        f'<span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={escape(representative.video_id, quote=True)}">YouTube ↗</span>'
        f'<span class="status-pill {state}">{state_label}</span></div>'
        '<div class="collab-event-copy">'
        f'<div class="collab-event-kicker"><span>{date_label}</span><span>{escape(candidate.confidence)}</span></div>'
        f'<h3>{escape(title)}</h3><div class="collab-avatars">{"".join(avatars)}</div>'
        f'<p>{pov_note} · 進入多人連動畫面</p></div></a>'
    )


def build_collab_hub_html(
    live: list[HomeStream],
    upcoming: list[HomeStream],
    ended: list[HomeStream],
) -> str:
    """Dedicated collab hub ordered by lifecycle first, then newest event date."""
    all_streams = [*live, *upcoming, *ended]
    candidates = detect_collab_candidates(all_streams)
    streams_by_id = {item.video_id: item for item in all_streams}
    def event_state(candidate: CollabCandidate) -> str:
        states = {streams_by_id[video_id].state for video_id in candidate.video_ids if video_id in streams_by_id}
        if "live" in states:
            return "live"
        if states & {"upcoming", "waiting"}:
            return "upcoming"
        return "ended"
    def event_time(candidate: CollabCandidate) -> datetime:
        values = [streams_by_id[video_id].start_at for video_id in candidate.video_ids
                  if video_id in streams_by_id and streams_by_id[video_id].start_at]
        return max(values) if values else datetime.min.replace(tzinfo=TAIPEI)
    candidates = tuple(sorted(
        candidates,
        key=lambda candidate: ({"live": 2, "upcoming": 1, "ended": 0}[event_state(candidate)], event_time(candidate)),
        reverse=True,
    ))
    sections = []
    for state, heading in (("live", "現在直播中"), ("upcoming", "稍後"), ("ended", "過去連動")):
        rows = [candidate for candidate in candidates if event_state(candidate) == state]
        if not rows:
            continue
        cards = "".join(_collab_event_card(candidate, streams_by_id) for candidate in rows)
        sections.append(
            f'<section class="section collab-hub-section"><div class="section-head"><div><h2>{heading}</h2></div></div>'
            f'<div class="collab-event-grid">{cards}</div></section>'
        )
    body = "".join(sections) or '<p class="empty-note">目前沒有偵測到可用的多人連動。</p>'
    content = (
        '<div class="page-head"><div><h1>多人連動</h1>'
        '<p>正在進行的連動優先；稍後場次與過去活動依時間排列。</p></div></div>' + body
    )
    css = """
.collab-event-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.collab-event-card{display:grid;grid-template-columns:minmax(220px,42%) 1fr;min-height:190px;overflow:hidden;border:1px solid var(--line);border-radius:20px;background:var(--surface);transition:.15s ease}
.collab-event-card:hover{transform:translateY(-2px);box-shadow:var(--shadow)}
.collab-event-thumb{position:relative;min-height:190px;background:var(--surface-2)}
.collab-event-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.collab-event-thumb .status-pill{position:absolute;left:12px;top:12px}
.collab-event-copy{padding:20px;display:flex;flex-direction:column;justify-content:center;min-width:0}
.collab-event-kicker{display:flex;gap:8px;color:var(--muted);font-size:11px;font-weight:800}
.collab-event-copy h3{margin:8px 0 14px;font-size:20px}
.collab-event-copy p{margin:12px 0 0;color:var(--muted);font-size:13px}
.collab-avatars{display:flex;align-items:center;padding-left:5px}
.collab-avatar{width:38px;height:38px;margin-left:-5px;border-radius:50%;overflow:hidden;border:2px solid var(--surface);background:var(--surface-2);display:grid;place-items:center;font-size:11px;font-weight:800}
.collab-avatar img{width:100%;height:100%;object-fit:cover}
@media(max-width:1040px){.collab-event-grid{grid-template-columns:1fr}}
@media(max-width:620px){.collab-event-card{grid-template-columns:1fr}.collab-event-thumb{min-height:0;aspect-ratio:16/9}}
"""
    return client_document(title="多人連動", active="collab", content=content, extra_css=css)
