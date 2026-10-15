"""Production-facing Client Watchalong page and session adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from functools import lru_cache
import json
import os
import secrets
from pathlib import Path
import sqlite3
from typing import Iterable
from urllib.parse import quote
from urllib.parse import urlencode

from client_home import _channel_accent
from client_runtime import client_runtime_root
from frontend_config import database_paths
from client_ui_shell import client_document
from client_home import _stream_group
from client_ui_shell import client_viewer_document
from frontend_time import TAIPEI
from frontend_watchalong_companion import build_companion_watchalong_html
from frontend_watchalong_extras import (
    WatchalongPttPayload,
    enhance_watchalong_html,
    load_watchalong_ptt_messages,
    subtitle_payload,
)
from shared_viewing_core import (
    parse_youtube_video_id,
    render_watchalong_session,
    watchalong_session_from_inputs,
)
from transcript_corpus import TranscriptCorpus
from transcript_ingest import TranscriptIngestService
from transcript_pipeline import TranscriptSegment
from live_stream_discovery import LiveDiscoveryCache
from watchalong_archive_store import (
    SavedWatchalongSourceMapping,
    load_latest_watchalong_source_mapping,
    load_watchalong_source_mapping,
    save_watchalong_source_mapping,
)
from watchalong_provider import detect_provider, is_http_source
from watchalong_ptt_catalog import load_recent_events, parse_watchalong_events
from watchalong_transcript import (
    confirmed_episode_start_cues,
    format_timestamp_ms,
    infer_watchalong_cues,
    parse_manual_transcript,
)
from watchalong_transcript_integration import load_watchalong_transcript
from watchalong_translation_integration import (
    inspect_watchalong_translation,
    watchalong_translation_view,
)
from watchalong_playback_telemetry import (
    PlaybackTelemetryReceiver,
    start_playback_telemetry_receiver,
)
from youtube_metadata import fetch_video, load_api_key


@dataclass(frozen=True, slots=True)
class ClientWatchalongCue:
    time_ms: int
    kind: str
    confidence: str
    text: str
    reason: str


@dataclass(frozen=True, slots=True)
class ClientWatchalongTelemetry:
    endpoint: str
    token: str
    session_id: str
    subtitle_endpoint: str


@lru_cache(maxsize=1)
def _client_watchalong_telemetry_receiver() -> PlaybackTelemetryReceiver:
    return start_playback_telemetry_receiver()


def new_client_watchalong_telemetry() -> ClientWatchalongTelemetry:
    """Create one local-only telemetry session without exposing it publicly."""

    receiver = _client_watchalong_telemetry_receiver()
    return ClientWatchalongTelemetry(
        endpoint=receiver.endpoint,
        token=receiver.token,
        session_id=secrets.token_urlsafe(12),
        subtitle_endpoint=receiver.subtitle_endpoint,
    )


def register_client_progressive_translation(
    telemetry: ClientWatchalongTelemetry,
    alignment: "ClientWatchalongAlignment | None",
    *,
    enabled: bool,
) -> bool:
    """4174 is read-only and never registers translation work."""

    return False


def run_client_progressive_translation_tick(session_id: str, token: str):
    """Fail closed if legacy code tries to execute translation on 4174."""

    raise PermissionError("4174 progressive translation is disabled")


@dataclass(frozen=True, slots=True)
class ClientWatchalongAlignment:
    transcript_available: bool
    segment_count: int
    starts: tuple[float, ...]
    cues: tuple[ClientWatchalongCue, ...]
    subtitles: tuple[dict, ...] = ()
    translation_status: str = "none"
    translated_segments: int = 0
    translation_total_segments: int = 0
    progressive_segments: tuple[TranscriptSegment, ...] = ()
    transcript_issue: str = ""
    a_subtitles: tuple[dict, ...] = ()
    b_subtitles: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchalongCard:
    title: str
    member: str
    master: str
    source: str
    status_label: str = ""


@dataclass(frozen=True, slots=True)
class RecentWatchalongHost:
    label: str
    video_id: str
    channel_name: str = ""
    avatar_url: str = ""


@dataclass(frozen=True, slots=True)
class RecentWatchalongCard:
    title: str
    day: str
    scheduled_time: str
    member_only: bool
    hosts: tuple[RecentWatchalongHost, ...]


def _normalize_member_name(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


def _load_channel_profiles() -> tuple[tuple[str, str], ...]:
    """Read channel names/avatars from the same local Catalog used by Client Today."""

    path = client_runtime_root() / "hololive_stream_catalog.sqlite3"
    if not path.exists():
        return ()
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.execute("PRAGMA query_only=ON")
    try:
        rows = connection.execute(
            "SELECT channel_name, avatar_url FROM channels "
            "WHERE channel_name IS NOT NULL AND channel_name != ''"
        ).fetchall()
    except sqlite3.Error:
        return ()
    finally:
        connection.close()
    return tuple((str(name or ""), str(avatar or "")) for name, avatar in rows)


def _hydrate_host(label: str, video_id: str, profiles: tuple[tuple[str, str], ...]) -> RecentWatchalongHost:
    needle = _normalize_member_name(label)
    best: tuple[int, str, str] | None = None
    for channel_name, avatar_url in profiles:
        haystack = _normalize_member_name(channel_name)
        if not needle or not haystack:
            continue
        if needle in haystack or haystack in needle:
            score = min(len(needle), len(haystack))
            if best is None or score > best[0]:
                best = (score, channel_name, avatar_url)
    if best is None:
        return RecentWatchalongHost(label=label, video_id=video_id)
    return RecentWatchalongHost(
        label=label,
        video_id=video_id,
        channel_name=best[1],
        avatar_url=best[2],
    )


def load_recent_watchalong_cards(
    *,
    database_path: str | Path | None = None,
    days: int = 30,
    limit: int = 60,
    now: datetime | None = None,
) -> tuple[RecentWatchalongCard, ...]:
    """Load current-cache + historical read-only Watchalong data for the Client."""

    current = now or datetime.now(TAIPEI)
    events = []

    # Fresh/current layer: reuse article bodies already persisted by discovery.
    runtime_root = client_runtime_root()
    cache = LiveDiscoveryCache(runtime_root / ".ptt_stream_discovery_cache.json")
    try:
        for offset in range(days):
            day = (current.date() - timedelta(days=offset)).isoformat()
            for snapshot in cache.for_day(day):
                events.extend(
                    parse_watchalong_events(
                        aid=snapshot.aid,
                        article_title=snapshot.title,
                        source_url=snapshot.source_url,
                        body_text=snapshot.body_text,
                    )
                )
    except (OSError, ValueError, TypeError):
        pass

    # Historical layer: fills older days from the body-complete Web DB.
    configured = database_path or os.environ.get("PTT_CLIENT_WATCHALONG_DB", "")
    if not configured:
        # 8501 owns the canonical Web history DB resolution (including env overrides).
        # 4174 must not silently drop historical events when no client-only env is set.
        _, configured = database_paths(root=runtime_root)
    if Path(configured).is_file():
        try:
            events.extend(load_recent_events(configured, days=days, now=current))
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pass

    # Newer/current evidence wins; identical master sets are one product card.
    events.sort(
        key=lambda event: (event.article_datetime, event.scheduled_time, event.aid),
        reverse=True,
    )
    deduped = []
    seen: set[tuple[str, ...]] = set()
    for event in events:
        signature = tuple(sorted(stream.video_id for stream in event.streams))
        if not signature or signature in seen:
            continue
        seen.add(signature)
        deduped.append(event)

    profiles = _load_channel_profiles()
    cards: list[RecentWatchalongCard] = []
    for event in deduped[:limit]:
        cards.append(
            RecentWatchalongCard(
                title=event.description,
                day=event.day,
                scheduled_time=event.scheduled_time,
                member_only=event.member_only,
                hosts=tuple(
                    _hydrate_host(stream.label, stream.video_id, profiles)
                    for stream in event.streams
                ),
            )
        )
    return tuple(cards)


WATCHALONG_CSS = r"""
.watch-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
body.watchalong-wide .client-main{max-width:1580px;width:100%}
.recent-watch-section{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:20px 20px 22px;box-shadow:0 8px 24px rgba(52,44,36,.035)}
.recent-watch-section .section-head{margin-top:0}
.watch-card-art{aspect-ratio:16/9;background:linear-gradient(135deg,#d7e8ee,#eadfd8);position:relative}
.watch-card-art:after{content:"WATCHALONG";position:absolute;left:14px;bottom:12px;color:rgba(255,255,255,.92);font-weight:900;letter-spacing:.08em;font-size:13px}
.recent-watch-card{position:relative;border:1px solid color-mix(in srgb,var(--member-accent,#9ab8c4) 16%,var(--line));border-radius:18px;overflow:hidden;background:#fff;box-shadow:0 2px 10px rgba(52,44,36,.035);padding:8px;cursor:pointer;transition:border-color .14s ease,box-shadow .14s ease,background .14s ease}
.recent-watch-card:hover,.recent-watch-card:focus-visible{transform:none;border-color:color-mix(in srgb,var(--member-accent,#7aa8bb) 72%,white);background:#fff;box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 34%,transparent),0 0 14px color-mix(in srgb,var(--member-accent,#7aa8bb) 30%,transparent),0 9px 22px rgba(52,44,36,.07);animation:memberGlow 1.8s ease-in-out infinite alternate;outline:none}
@keyframes memberGlow{from{box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 28%,transparent),0 0 8px color-mix(in srgb,var(--member-accent,#7aa8bb) 20%,transparent),0 9px 22px rgba(52,44,36,.06)}to{box-shadow:0 0 0 1px color-mix(in srgb,var(--member-accent,#7aa8bb) 48%,transparent),0 0 17px color-mix(in srgb,var(--member-accent,#7aa8bb) 38%,transparent),0 9px 22px rgba(52,44,36,.07)}}
.recent-watch-thumb{aspect-ratio:16/9;background:#eef2f3;overflow:hidden;border-radius:16px}.recent-watch-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.recent-watch-copy{padding:12px 2px 2px}.recent-watch-meta{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:8px;color:var(--muted);font-size:11px;font-weight:700}
.recent-watch-copy h3{margin:0 0 10px;font-size:15px;line-height:1.45}.recent-watch-hosts{display:flex;gap:8px;flex-wrap:wrap}
.recent-watch-host{display:inline-flex;align-items:center;gap:8px;max-width:100%;border:0;border-radius:999px;padding:3px 8px 3px 3px;background:transparent;color:var(--member-accent,var(--muted));font-size:12px;font-weight:750;text-decoration:none}
.recent-watch-host:hover{background:color-mix(in srgb,var(--member-accent,#7aa8bb) 7%,white)}
.recent-host-avatar{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;padding:2px;background:white;border:2px solid var(--member-accent,#9ab8c4);box-shadow:0 0 0 2px color-mix(in srgb,var(--member-accent,#9ab8c4) 18%,transparent);overflow:hidden}
.recent-host-avatar img{width:100%;height:100%;border-radius:50%;object-fit:cover}.recent-host-avatar span{font-size:9px;font-weight:800;color:var(--member-accent,#4f7f93)}
.watchalong-filter{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 14px}.watchalong-filter-button{background:var(--surface);border:1px solid var(--line);border-radius:999px;cursor:pointer;padding:7px 12px;font-size:12px}.watchalong-filter-button.active{background:var(--text);color:#fff}
.recent-watch-search-label{display:block;margin:10px 0 7px;font-size:12px;font-weight:700}.recent-watch-search{width:100%;max-width:420px;min-height:38px;padding:8px 12px;border:1px solid var(--line);border-radius:10px;margin-bottom:16px}.recent-watch-no-matches{color:var(--muted);font-size:13px}.recent-watch-card[hidden],.recent-watch-no-matches[hidden]{display:none!important}
.recent-watch-note{margin:4px 0 14px;color:var(--muted);font-size:12px;line-height:1.55}
.selection-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.selection-link{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:999px;padding:8px 12px;background:#fff;color:var(--text);font-size:12px;font-weight:750;text-decoration:none}.selection-link:hover{background:var(--surface-2)}
.manual-shell{padding:20px}.manual-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:24px;align-items:start}
.selected-master{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fff;margin-top:12px}.selected-master img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}.selected-master-copy{padding:12px}.selected-master-copy strong{display:block;margin-bottom:5px}.selected-master-copy span{color:var(--muted);font-size:12px}
.manual-copy h2{margin:7px 0 8px;font-size:22px}.manual-copy p{margin:0;color:var(--muted);line-height:1.65}
.form-grid{display:grid;gap:12px}label{display:grid;gap:7px;font-size:12px;font-weight:700;color:#5e5a54}
.actions{display:flex;justify-content:flex-end;margin-top:14px}.boundary{margin:12px 0 0;color:var(--muted);font-size:11px;line-height:1.55}
@media(max-width:1250px){.watch-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:900px){.watch-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.watch-grid{grid-template-columns:1fr}}
.view-mode-choice{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}.view-mode-choice label{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:8px 12px;background:#fff;cursor:pointer}.view-mode-choice label:has(input:checked){background:var(--text);color:#fff;border-color:var(--text)}.view-mode-choice input{position:absolute;opacity:0;pointer-events:none}
.source-choice{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.choice-card{position:relative;display:block;border:1px solid var(--line);border-radius:14px;padding:14px;background:#fff;cursor:pointer}
.choice-card input{position:absolute;opacity:0;pointer-events:none}.choice-card strong{display:block;margin-bottom:4px}.choice-card span{font-size:12px;color:var(--muted);line-height:1.5}
.choice-card:has(input:checked){border-color:#9fc7d7;background:#f2f9fb;box-shadow:0 0 0 2px #dcecf2 inset}
.source-panel{display:grid;gap:12px}.source-panel[hidden]{display:none}.mode-tabs{display:flex;gap:8px;flex-wrap:wrap}.mode-tab{border:1px solid var(--line);border-radius:999px;padding:8px 12px;background:#fff;cursor:pointer;font-weight:700}
.mode-tab.active{background:var(--text);color:#fff;border-color:var(--text)}
.builder-advanced{margin:0 0 14px;border:1px solid var(--line);border-radius:12px;background:#faf9f7}
.builder-advanced>summary{cursor:pointer;padding:10px 12px;font-size:12px;font-weight:750;color:#625e58;list-style:none}
.builder-advanced>summary::-webkit-details-marker{display:none}
.builder-advanced>summary:after{content:"＋";float:right;color:#9a958d}
.builder-advanced[open]>summary:after{content:"－"}
.builder-advanced[open]{padding-bottom:12px}.builder-advanced[open]>.view-mode-choice,.builder-advanced[open]>.inline-grid,.builder-advanced[open]>.helper{margin-left:12px;margin-right:12px}
.inline-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.helper{color:var(--muted);font-size:11px;line-height:1.55}
@media(max-width:760px){.manual-grid,.watch-grid,.source-choice,.inline-grid{grid-template-columns:1fr}}
"""

WATCHALONG_INNER_CSS = r"""
html,body{background:#111!important;color:#eee!important}
body{padding:10px!important}
#layout-controls{padding:2px 0 4px}
.alignment-state{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 8px;padding:9px 11px;border:1px solid #333;border-radius:10px;background:#151515;font-size:12px}
.alignment-state strong{font-size:12px}.alignment-state span{color:#aab0b3}
.alignment-state.ready{border-color:#355f4d;background:#122019}.alignment-state.ready strong{color:#9ee5be}
.alignment-state.manual{border-color:#5a4e2e;background:#211d13}.alignment-state.manual strong{color:#f0ce75}
#client-quick-controls{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:0 0 10px}
.cue-points{margin:-2px 0 10px;border:1px solid #2f2f2f;border-radius:10px;background:#131313}
.cue-points>summary{cursor:pointer;padding:8px 11px;color:#aeb5b8;font-size:11px;font-weight:700}
.cue-list{padding:0 11px 9px;color:#8f9598;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;display:grid;gap:3px}
.cue-diagnostics{border-top:1px solid #292929;margin-top:2px}.cue-diagnostics>summary{cursor:pointer;padding:8px 11px;color:#8f9598;font-size:11px}.cue-diagnostic-head,.cue-diagnostic-row{display:grid;grid-template-columns:70px 58px 58px minmax(180px,1fr) minmax(160px,1fr);gap:8px;padding:6px 11px;align-items:start}.cue-diagnostic-head{color:#777;font-size:10px;font-weight:800;border-top:1px solid #202020;border-bottom:1px solid #202020}.cue-diagnostic-row{color:#aaa;font-size:10px;border-bottom:1px solid #1d1d1d}.cue-diagnostic-row span:nth-child(4),.cue-diagnostic-row span:nth-child(5){white-space:normal;line-height:1.4}
#client-quick-controls .spacer{flex:1}
#immersive{display:none!important}
#client-quick-controls button{border:1px solid #3d3d3d;background:#1c1c1c;color:#eee;border-radius:9px;padding:7px 10px;cursor:pointer}
#client-quick-controls button.primary{background:#eef1f2;color:#151515;border-color:#eef1f2;font-weight:800}
#client-quick-controls button.immersive{background:#252525}
#client-advanced{margin-top:10px;border:1px solid #2f2f2f;border-radius:12px;background:#131313}
#client-advanced>summary{cursor:pointer;padding:10px 12px;color:#c8c8c8;font-size:12px;font-weight:700;list-style:none}
#client-advanced>summary::-webkit-details-marker{display:none}
#client-advanced>summary:after{content:"＋";float:right;color:#777}
#client-advanced[open]>summary:after{content:"－"}
.card,#controls{border-color:#2f2f2f!important;border-radius:12px!important;overflow:hidden!important;background:#151515!important}
.head{background:#171717!important;padding:9px 11px!important;border-bottom-color:#303030!important}
#grid{gap:12px!important}
#controls{margin-top:0!important;padding:12px!important;border:0!important;border-top:1px solid #2f2f2f!important;border-radius:0 0 12px 12px!important}
button{border-radius:9px!important;padding:7px 10px!important}
button.primary{background:#eef1f2!important;color:#151515!important;border-color:#eef1f2!important;font-weight:800!important}
button.active{background:#dce8ed!important;color:#1f2b30!important;border-color:#dce8ed!important}
.note{color:#8f9598!important;font-size:11px!important}
#subtitle-toolbar{align-items:center!important;padding:5px 7px!important;border-bottom:1px solid #242424}
#subtitle-toolbar:before{content:"字幕";margin-right:auto;color:#8f9598;font-size:10px;font-weight:800;letter-spacing:.04em}
/* 4174 presentation only: put the shared 8501 subtitle overlay above native YouTube captions. */
#source-subtitle-overlay{top:auto!important;bottom:22%!important;left:7%!important;right:7%!important;justify-content:center;pointer-events:none;background:transparent!important}
#source-subtitle-overlay .overlay-jp,#source-subtitle-overlay .overlay-zh{background:transparent!important;text-shadow:-2px -2px 2px #000,2px -2px 2px #000,-2px 2px 2px #000,2px 2px 2px #000,0 2px 8px #000}
body.client-immersive #source-subtitle-overlay{bottom:23%!important}

#ptt-head{padding:6px 9px!important}
#client-source-adjustments{border-top:1px solid #303030;background:#121212}
#client-source-adjustments>summary{cursor:pointer;padding:8px 10px;color:#aeb5b8;font-size:11px;font-weight:700;list-style:none}
#client-source-adjustments>summary::-webkit-details-marker{display:none}
#client-source-adjustments>summary:after{content:"＋";float:right;color:#777}
#client-source-adjustments[open]>summary:after{content:"－"}
#source-adjustments{background:#121212!important;border-top:1px solid #252525!important}
body.client-immersive #layout-controls,
body.client-immersive #client-quick-controls,
body.client-immersive #client-advanced,
body.client-immersive .alignment-state,
body.client-immersive .cue-points,
body.client-immersive #client-source-adjustments,
body.client-immersive .card>.head,
body.client-immersive #subtitle-toolbar{display:none!important}
body.client-immersive{padding:0!important;overflow:hidden}
body.client-immersive #grid{height:100dvh!important;min-height:0!important;gap:4px!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;align-items:start}
body.client-immersive #grid.focus-source{height:100dvh!important;min-height:0!important;gap:4px!important;grid-template-columns:minmax(220px,.30fr) minmax(0,1fr)!important;align-items:stretch!important}
body.client-immersive .card{border-color:#151515!important;min-height:0!important}
body.client-immersive #master-card,body.client-immersive #source-card{height:auto!important;min-height:0!important;display:flex;flex-direction:column}
body.client-immersive #grid.focus-source #master-card{height:100dvh!important;overflow:hidden}
body.client-immersive #grid.focus-source #source-card{height:100dvh!important;overflow:hidden}
body.client-immersive #master-card>.player-wrap{height:auto!important;aspect-ratio:16/9!important;flex:0 0 auto;min-height:0;max-height:min(48dvh,calc((50vw - 8px)*9/16));}
body.client-immersive #grid:not(.focus-source) #source-card>.player-wrap{height:auto!important;aspect-ratio:16/9!important;flex:0 0 auto;min-height:0;max-height:min(48dvh,calc((50vw - 8px)*9/16));}
body.client-immersive #grid.focus-source #source-card>.player-wrap{height:100%!important;aspect-ratio:auto!important;flex:1 1 auto!important;min-height:0}
body.client-immersive #master-card #subtitle-shell{flex:0 0 auto}
body.client-immersive #master-card #ptt-panel{height:auto!important;min-height:0!important;max-height:none!important;flex:1 1 0!important;overflow:hidden!important}
body.client-immersive #master-card #ptt-feed{height:auto!important;min-height:0!important;max-height:none!important;flex:1 1 0!important;overflow-y:auto!important}
body.client-immersive #master-card>.player-wrap iframe,body.client-immersive #source-card>.player-wrap iframe{width:100%!important;height:100%!important;max-height:100%!important;object-fit:contain}
body.client-immersive #source-card #client-source-adjustments{display:none!important}
@media(max-width:820px){
  #client-quick-controls .spacer{display:none}
  body.client-immersive{overflow-x:hidden!important;overflow-y:auto!important}
  body.client-immersive #grid,body.client-immersive #grid.focus-source{height:auto!important;min-height:100dvh!important;grid-template-columns:1fr!important;overflow:visible!important}
  body.client-immersive #master-card,body.client-immersive #source-card{height:auto!important;min-height:0!important;overflow:visible!important}
  body.client-immersive #master-card>.player-wrap,body.client-immersive #source-card>.player-wrap{height:auto!important;max-height:none!important;aspect-ratio:16/9!important;flex:0 0 auto!important}
  body.client-immersive #master-card #ptt-panel{height:55vh!important;min-height:320px!important;max-height:none!important;flex:0 0 auto!important}
}
"""


def _card_html(card: WatchalongCard) -> str:
    params = urlencode({"master": card.master, "source": card.source})
    status = (
        f'<span class="status-pill upcoming">{escape(card.status_label)}</span>'
        if card.status_label
        else ""
    )
    return (
        f'<a class="client-card" href="/watchalong/session?{params}">'
        '<div class="watch-card-art" aria-hidden="true"></div>'
        f'<div class="card-copy">{status}'
        f'<h3>{escape(card.title)}</h3>'
        f'<p>{escape(card.member)}</p></div></a>'
    )


def _recent_watchalong_section(cards: Iterable[RecentWatchalongCard]) -> str:
    rendered: list[str] = []
    for card in cards:
        if not card.hosts:
            continue
        thumb_id = card.hosts[0].video_id
        thumb = f"https://i.ytimg.com/vi/{escape(thumb_id, quote=True)}/hqdefault.jpg"
        when = " ".join(part for part in (card.day, card.scheduled_time) if part)
        member_badge = '<span class="status-pill upcoming">會員限定</span>' if card.member_only else ""
        host_links = ""
        for host in card.hosts:
            display_name = host.channel_name or host.label
            avatar_text = next((char for char in display_name if char.isalnum()), "H").upper()
            avatar = (
                f'<img src="{escape(host.avatar_url, quote=True)}" alt="" loading="lazy">'
                if host.avatar_url
                else f'<span aria-hidden="true">{escape(avatar_text)}</span>'
            )
            accent = _channel_accent(display_name)
            accent_style = f' style="--member-accent:{accent}"' if accent else ""
            host_links += (
                f'<a class="recent-watch-host" href="/watchalong?{urlencode({"master": host.video_id})}#manual"{accent_style}>'
                f'<span class="recent-host-avatar">{avatar}</span>'
                f'<span>{escape(display_name)}</span></a>'
            )
        default_host = card.hosts[0]
        default_href = f"/watchalong?{urlencode({'master': default_host.video_id})}#manual"
        default_name = default_host.channel_name or default_host.label
        accent = _channel_accent(default_name)
        accent_style = f' style="--member-accent:{accent}"' if accent else ""
        search_text = " ".join((card.title, card.day, card.scheduled_time, *(
            host.channel_name or host.label for host in card.hosts
        ))).casefold()
        groups = {
            _stream_group(host.channel_name or host.label, host.label)
            for host in card.hosts
        }
        group_value = " ".join(sorted(groups))
        rendered.append(
            f'<article class="recent-watch-card" data-group="{escape(group_value, quote=True)}" data-search="{escape(search_text, quote=True)}" role="link" tabindex="0" data-href="{escape(default_href, quote=True)}"{accent_style} '
            'onclick="if(!event.target.closest(\'.recent-watch-host\')) location.href=this.dataset.href" '
            'onkeydown="if(event.key===\'Enter\') location.href=this.dataset.href">'
            f'<div class="recent-watch-thumb" style="position:relative"><img src="{thumb}" alt="" loading="lazy">'
            f'<span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={escape(thumb_id, quote=True)}">YouTube ↗</span></div>'
            '<div class="recent-watch-copy">'
            f'<div class="recent-watch-meta"><span>{escape(when)}</span>{member_badge}</div>'
            f'<h3>{escape(card.title)}</h3>'
            f'<div class="recent-watch-hosts">{host_links}</div>'
            '</div></article>'
        )
    if not rendered:
        return ""
    return (
        '<section class="section recent-watch-section" id="recent-watchalong">'
        '<div class="section-head"><div><h2>近期同時視聽</h2>'
        '<p class="recent-watch-note">選擇想看的同時視聽，接著設定片源。</p>'
        '</div></div>'
        '<div class="watchalong-filter" role="group" aria-label="同時視聽群組">'
        '<button class="watchalong-filter-button active" type="button" data-watch-group="all">全部</button>'
        '<button class="watchalong-filter-button" type="button" data-watch-group="hololive">Hololive</button>'
        '<button class="watchalong-filter-button" type="button" data-watch-group="holostars">HOLOSTARS</button>'
        '<button class="watchalong-filter-button" type="button" data-watch-group="mekpark">mekPark</button>'
        '</div>'
        '<label class="recent-watch-search-label" for="recentWatchSearch">搜尋近期同時視聽</label>'
        '<input class="recent-watch-search" id="recentWatchSearch" type="search"'
        ' placeholder="搜尋標題、成員、日期…" autocomplete="off">'
        '<p class="recent-watch-no-matches" id="recentWatchNoMatches" hidden>沒有符合的近期同時視聽。</p>'
        f'<div class="watch-grid" id="recentWatchGrid">{"".join(rendered)}</div></section>'
    )


def _section(title: str, cards: Iterable[WatchalongCard]) -> str:
    rendered = "".join(_card_html(card) for card in cards)
    if not rendered:
        return ""
    return (
        '<section class="section">'
        f'<div class="section-head"><div><h2>{escape(title)}</h2></div></div>'
        f'<div class="watch-grid">{rendered}</div></section>'
    )


def _client_watchalong_archive_path() -> Path:
    return client_runtime_root() / "data" / "watchalong" / "watchalong_archive.sqlite3"


def load_client_watchalong_source_mapping(master: str) -> SavedWatchalongSourceMapping | None:
    if not master.strip():
        return None
    try:
        return load_watchalong_source_mapping(master, _client_watchalong_archive_path())
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return None


def load_latest_client_watchalong_source_mapping() -> SavedWatchalongSourceMapping | None:
    try:
        return load_latest_watchalong_source_mapping(_client_watchalong_archive_path())
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return None


def save_client_watchalong_source_mapping(
    *,
    master: str,
    playlist_url: str,
    playlist_start_index: int,
    source_urls: Iterable[str],
    waiting_urls: Iterable[str] = (),
) -> SavedWatchalongSourceMapping:
    return save_watchalong_source_mapping(
        master_url=master,
        playlist_url=playlist_url,
        playlist_start_index=playlist_start_index,
        source_urls=tuple(source_urls),
        waiting_urls=tuple(waiting_urls),
        path=_client_watchalong_archive_path(),
    )


def build_watchalong_landing_html(
    *,
    live: Iterable[WatchalongCard] = (),
    upcoming: Iterable[WatchalongCard] = (),
    recent: Iterable[WatchalongCard] = (),
    recent_pool: Iterable[RecentWatchalongCard] = (),
    error: str = "",
    master_value: str = "",
    source_value: str = "",
    playlist_value: str = "",
    playlist_start_value: int = 1,
) -> str:
    """Build the production Client Watchalong landing page."""

    pool = tuple(recent_pool)
    sections = "".join(
        (
            _section("現在正在同時視聽", live),
            _section("即將開始", upcoming),
            _recent_watchalong_section(pool),
            _section("最近的同時視聽", recent),
        )
    )
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    playlist_selected = bool(playlist_value.strip())
    single_tab_class = "mode-tab" if playlist_selected else "mode-tab active"
    playlist_tab_class = "mode-tab active" if playlist_selected else "mode-tab"
    youtube_mode_value = "playlist" if playlist_selected else "single"
    single_hidden = " hidden" if playlist_selected else ""
    playlist_hidden = "" if playlist_selected else " hidden"
    restored_playlist_note = (
        '<div class="helper" style="margin-bottom:8px">已恢復這支同時視聽先前使用的 Playlist 設定。</div>'
        if playlist_selected
        else ""
    )
    selected_card = None
    selected_label = ""
    if master_value:
        for candidate in pool:
            for host in candidate.hosts:
                if host.video_id == master_value:
                    selected_card = candidate
                    selected_label = host.channel_name or host.label
                    break
            if selected_card:
                break

    if selected_card:
        selected_thumb = f"https://i.ytimg.com/vi/{escape(master_value, quote=True)}/hqdefault.jpg"
        selected_master_html = (
            '<span class="eyebrow">已選擇同時視聽</span>'
            f'<h2>{escape(selected_card.title)}</h2>'
            '<p>主直播已選好，右邊只要選擇要同步的片源。</p>'
            '<div class="selection-actions"><a class="selection-link" href="/watchalong?fresh=1#manual">取消選擇</a>'
            '<a class="selection-link" href="#recent-watchalong">回到上方選擇</a></div>'
            '<div class="selected-master" style="position:relative">'
            f'<img src="{selected_thumb}" alt="" loading="lazy">'
            f'<span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={escape(master_value, quote=True)}">YouTube ↗</span>'
            '<div class="selected-master-copy">'
            f'<strong>{escape(selected_label)}</strong>'
            f'<span>{escape(selected_card.day)} {escape(selected_card.scheduled_time)}</span>'
            '</div></div>'
            f'<input type="hidden" name="master" value="{escape(master_value, quote=True)}">'
        )
    else:
        selected_master_html = (
            '<span class="eyebrow">手動建立</span>'
            '<h2>找不到想看的同時視聽直播？</h2>'
            '<p>貼上 Hololive 主直播，接著在右邊選擇片源。</p>'
            '<div class="selection-actions"><a class="selection-link" href="#recent-watchalong">回到上方選擇</a></div>'
            '<div class="form-grid" style="margin-top:14px">'
            '<label>Hololive 主直播'
            f'<input name="master" autocomplete="off" inputmode="url" required value="{escape(master_value, quote=True)}" placeholder="YouTube URL 或 Video ID">'
            '</label></div>'
        )
    content = f"""
<div class="page-head"><div><h1>同時視聽</h1></div></div>
{sections}
<section class="section">
  <div class="tool-card manual-shell" id="manual">
    {error_html}
    <form method="get" action="/watchalong/session" id="watchalongBuilder" class="manual-grid">
      <div class="manual-copy">
        {selected_master_html}
      </div>
      <div>
        <details class="builder-advanced">
          <summary>觀看模式（通常不用調整）</summary>
          <div class="view-mode-choice">
            <label><input type="radio" name="view_mode" value="auto" checked><span>自動判定</span></label>
            <label><input type="radio" name="view_mode" value="archive"><span>舊檔 / VOD</span></label>
            <label><input type="radio" name="view_mode" value="live"><span>即時直播</span></label>
          </div>
          <div class="helper">如果自動判定失敗，再手動指定舊檔或即時直播。</div>
        </details>
        <div style="margin:0 0 8px;font-size:12px;font-weight:800;color:#5e5a54">片源類型</div>
        <div class="source-choice">
          <label class="choice-card">
            <input type="radio" name="source_kind" value="youtube" checked>
            <strong>YouTube</strong><span>可自動控制與同步；支援單支影片或 Playlist。</span>
          </label>
          <label class="choice-card">
            <input type="radio" name="source_kind" value="external">
            <strong>外部平台</strong><span>動畫瘋、Prime Video 或其他網站；會在外部視窗播放並提供手動對齊。</span>
          </label>
        </div>
        <div id="youtubePanel" class="source-panel">
          {restored_playlist_note}
          <div class="mode-tabs">
            <button type="button" class="{single_tab_class}" data-youtube-mode="single">單支影片</button>
            <button type="button" class="{playlist_tab_class}" data-youtube-mode="playlist">Playlist</button>
          </div>
          <input type="hidden" name="youtube_mode" id="youtubeMode" value="{youtube_mode_value}">
          <div id="singleFields"{single_hidden}>
            <label>YouTube 片源
              <input name="source" autocomplete="off" inputmode="url" value="{escape(source_value, quote=True)}" placeholder="YouTube URL 或 Video ID">
            </label>
          </div>
          <div id="playlistFields"{playlist_hidden}>
            <label>Playlist URL
              <input name="playlist" autocomplete="off" inputmode="url" value="{escape(playlist_value, quote=True)}" placeholder="https://www.youtube.com/playlist?list=...">
            </label>
            <details class="builder-advanced">
              <summary>Playlist 進階設定</summary>
              <div class="inline-grid">
                <label>從第幾集開始
                  <input name="playlist_start" type="number" min="1" value="{max(1, int(playlist_start_value))}">
                </label>
                <label>匯入幾集（可留空）
                  <input name="playlist_count" type="number" min="1" placeholder="全部">
                </label>
              </div>
              <div class="helper">舊檔會依主直播中的開始觀看時間點自動決定需要的集數；即時直播會先載入目前需要的集數，其餘放在等待序列。只有需要覆寫時才需要調整。</div>
            </details>
          </div>
        </div>
        <div id="externalPanel" class="source-panel" hidden>
          <label>外部片源網址
            <input name="external_source" autocomplete="off" inputmode="url" placeholder="動畫瘋 / Prime Video / 其他 http(s) 網址">
          </label>
          <div class="helper">外部平台會留在你正常登入的瀏覽器分頁；Viewer 只提供對齊工具，不讀取帳號，也不繞過登入、廣告或播放限制。</div>
        </div>
        <div class="actions"><button class="primary-action" type="submit">繼續設定並開始</button></div>
      </div>
    </form>
  </div>
</section>
"""
    builder_js = r"""
const recentWatchSearch=document.getElementById('recentWatchSearch');
let activeWatchGroup='all';
function filterRecentWatchalong(){
  const query=recentWatchSearch?.value.trim().toLocaleLowerCase()||'';
  let visible=0;
  document.querySelectorAll('#recentWatchGrid .recent-watch-card').forEach(card=>{
    const groupMatch=activeWatchGroup==='all'||(card.dataset.group||'').split(' ').includes(activeWatchGroup);
    const textMatch=!query||(card.dataset.search||'').toLocaleLowerCase().includes(query);
    card.hidden=!(groupMatch&&textMatch);
    if(!card.hidden)visible++;
  });
  const empty=document.getElementById('recentWatchNoMatches');
  if(empty)empty.hidden=visible!==0;
}
recentWatchSearch?.addEventListener('input',filterRecentWatchalong);
document.querySelectorAll('[data-watch-group]').forEach(button=>button.addEventListener('click',()=>{
  activeWatchGroup=button.dataset.watchGroup||'all';
  document.querySelectorAll('[data-watch-group]').forEach(item=>item.classList.toggle('active',item===button));
  filterRecentWatchalong();
}));
const youtubePanel=document.getElementById('youtubePanel');
const externalPanel=document.getElementById('externalPanel');
const youtubeMode=document.getElementById('youtubeMode');
const singleFields=document.getElementById('singleFields');
const playlistFields=document.getElementById('playlistFields');
function applySourceKind(){
  const kind=document.querySelector('input[name="source_kind"]:checked')?.value||'youtube';
  youtubePanel.hidden=kind!=='youtube';
  externalPanel.hidden=kind!=='external';
}
document.querySelectorAll('input[name="source_kind"]').forEach(input=>input.addEventListener('change',applySourceKind));
document.querySelectorAll('[data-youtube-mode]').forEach(button=>button.addEventListener('click',()=>{
  youtubeMode.value=button.dataset.youtubeMode;
  document.querySelectorAll('[data-youtube-mode]').forEach(item=>item.classList.toggle('active',item===button));
  singleFields.hidden=youtubeMode.value!=='single';
  playlistFields.hidden=youtubeMode.value!=='playlist';
}));
applySourceKind();
"""
    return client_document(
        title="同時視聽",
        active="watchalong",
        content=content,
        extra_css=WATCHALONG_CSS,
        extra_script=builder_js,
        body_class="watchalong-wide",
    )


def _clientize_watchalong_inner(
    inner: str,
    *,
    episode_starts: tuple[float, ...] = (),
    source_count: int = 1,
    alignment_report: ClientWatchalongAlignment | None = None,
    progressive_enabled: bool = False,
    progressive_requested: bool = False,
    progressive_session_id: str = "",
    progressive_token: str = "",
    master_video_id: str = "",
    ab_translation_enabled: bool = False,
    ab_translation_ready: bool = False,
) -> str:
    """Add Client-only status and recovery controls around verified timing logic."""

    # 4174 is presentation-only for translation artifacts. Legacy callers may
    # still pass these flags, but they must never expose or start translation.
    progressive_enabled = False
    progressive_requested = False

    # Product-facing labels only; keep the verified shared renderer untouched.
    inner = inner.replace('>對照</button>', '>雙畫面</button>', 1)
    inner = inner.replace('>Focus 動畫</button>', '>動畫優先</button>', 1)
    inner = inner.replace(
        '<div class="head">Hololive 直播（主時間軸）</div>',
        '<div class="head">Hololive 主直播</div>',
        1,
    )
    inner = inner.replace(
        '<div class="head">同時視聽來源（YouTube）</div>',
        '<div class="head">片源（YouTube）</div>',
        1,
    )
    inner = inner.replace("字幕會跟隨兔子時間軸", "字幕會跟隨主直播時間", 1)
    inner = inner.replace(">畫面字幕</button>", ">片源畫面字幕</button>", 1)
    inner = inner.replace(">彈幕</button>", ">字幕彈幕</button>", 1)
    inner = inner.replace("PTT 載入中", "PTT 同步留言 · 載入中", 1)
    inner = inner.replace(">同步播放／啟動跟隨</button>", ">啟動同步</button>")
    inner = inner.replace("同步播放／重新啟動", "重新同步")
    inner = inner.replace(
        "可以按「同步播放／啟動跟隨」一次啟動兩邊；Archive Pending 時會先用這次點擊啟用來源播放器，再立刻停回 00:00，等 transcript cue 到點後自動播放。直接點 master 播放仍只做 best-effort 跟隨。Focus／對照只切版面，不重建播放器或同步 session。片源上方的兩組微調可用來處理不同地區片源時間差：單集只改目前影片；片源微調會從目前這集開始延續到後面的影片。",
        "按「啟動同步」後，播放器會依目前模式開始跟隨。舊檔若有自動對齊時間點，片源會在正確時間自動開始；需要微調時再展開進階設定。",
        1,
    )
    inner = inner.replace(
        "Archive 自動模式：不需要手動建立對齊點；請按一次「同步播放／啟動跟隨」。Pending 時會先啟用來源播放器，等 transcript cue 到點後自動選集／seek／播放。手動對齊只在進階區作為覆寫。",
        "已準備自動對齊。按一次「啟動同步」後，片源會依主直播時間自動選集與對齊。",
        1,
    )
    inner = inner.replace(
        "Live／手動模式：先處理來源端登入／畫質／前置廣告，再建立對齊點；同步播放可一次啟動兩邊。",
        "目前使用手動對齊。先確認片源可正常播放，再以目前位置建立對齊點。",
        1,
    )
    inner = inner.replace(
        "即時模式：右側先待機。直播主倒數要開始時，再按「同步播放／啟動跟隨」；本集播完後也只會載入下一集到 00:00 待機。",
        "即時模式：片源會先待機。準備開始時按「啟動同步」；播完一集後，下一集會停在 00:00 等待。",
        1,
    )
    inner = inner.replace("Archive Pending", "舊檔等待中")
    inner = inner.replace("transcript cue", "自動對齊時間點")
    inner = inner.replace("best-effort", "盡可能")
    inner = inner.replace("Focus／對照", "畫面模式")
    if '<div id="source-adjustments">' in inner:
        inner = inner.replace(
            '<div id="source-adjustments">',
            '<details id="client-source-adjustments"><summary>片源時間微調</summary><div id="source-adjustments">',
            1,
        )
        inner = inner.replace(
            '</div></section></div>\n<div id="controls">',
            '</div></details></section></div>\n<div id="controls">',
            1,
        )

    def _clock(seconds: float) -> str:
        value = max(0, int(seconds))
        hours, remainder = divmod(value, 3600)
        minutes, secs = divmod(remainder, 60)
        return (
            f"{hours:02d}:{minutes:02d}:{secs:02d}"
            if hours
            else f"{minutes:02d}:{secs:02d}"
        )

    if episode_starts:
        count = len(episode_starts)
        scope = (
            f"共 {source_count} 集，已準備 {count} 個自動對齊時間點"
            if source_count > 1
            else "已準備自動對齊時間點"
        )
        partial = (
            f" · 目前可自動對齊前 {count} 集"
            if source_count > count
            else ""
        )
        translation_note = ""
        if alignment_report is not None:
            translation_status = getattr(alignment_report, "translation_status", "none")
            if translation_status == "ready":
                translation_note = " · 中文字幕已載入"
            elif translation_status == "partial":
                translation_note = (
                    f" · 中文字幕 {getattr(alignment_report, 'translated_segments', 0)}/"
                    f"{getattr(alignment_report, 'translation_total_segments', 0)} 段"
                )
        alignment_html = (
            '<div id="client-alignment-state" class="alignment-state ready">'
            f'<strong>✓ 自動對齊已啟用</strong><span>{scope}{partial}{translation_note}</span>'
            '</div>'
        )
        cue_rows = "".join(
            f"<div>第 {index + 1} 集 · 主直播 {_clock(start)} → 片源 00:00</div>"
            for index, start in enumerate(episode_starts)
        )
        diagnostics = ""
        if alignment_report is not None and alignment_report.cues:
            labels = {
                "start": "開始",
                "pause": "暫停",
                "resume": "繼續",
                "next_episode": "下一集",
            }
            diagnostic_rows = "".join(
                '<div class="cue-diagnostic-row">'
                f'<span>{format_timestamp_ms(cue.time_ms)}</span>'
                f'<span>{escape(labels.get(cue.kind, cue.kind))}</span>'
                f'<span>{escape(cue.confidence)}</span>'
                f'<span>{escape(cue.text)}</span>'
                f'<span>{escape(cue.reason)}</span>'
                '</div>'
                for cue in alignment_report.cues
            )
            diagnostics = (
                '<details class="cue-diagnostics"><summary>查看判定細節</summary>'
                '<div class="cue-diagnostic-head"><span>時間</span><span>類型</span><span>信心</span><span>原文</span><span>原因</span></div>'
                f'<div class="cue-diagnostic-list">{diagnostic_rows}</div></details>'
            )
        cue_details = (
            '<details id="client-cue-points" class="cue-points"><summary>同步資訊</summary>'
            f'<div class="cue-list">{cue_rows}</div>{diagnostics}</details>'
        )
    else:
        transcript_note = (
            f"已讀取主直播字幕（{alignment_report.segment_count} 段），但沒有找到可用的開始觀看時間點。"
            if alignment_report is not None and alignment_report.transcript_available
            else "共用資料來源目前沒有這支主直播的可用 Transcript；8501 尚未儲存的編輯內容不會自動出現在 4174。"
        )
        if alignment_report is not None and alignment_report.transcript_issue:
            transcript_note = alignment_report.transcript_issue
        if alignment_report is not None:
            translation_status = getattr(alignment_report, "translation_status", "none")
            if translation_status == "ready":
                transcript_note += " 中文字幕已載入。"
            elif translation_status == "partial":
                transcript_note += (
                    f" 中文字幕已完成 {getattr(alignment_report, 'translated_segments', 0)}/"
                    f"{getattr(alignment_report, 'translation_total_segments', 0)} 段。"
                )
        alignment_html = (
            '<div id="client-alignment-state" class="alignment-state manual">'
            '<strong>○ 目前需要手動對齊</strong>'
            f'<span>{escape(transcript_note)} 播放器會先保持獨立，你仍可在下方手動建立對齊點。</span>'
            '</div>'
        )
        cue_details = ""

    progressive_html = ""
    if progressive_enabled:
        progressive_html = (
            '<div id="client-progressive-state" class="alignment-state ready">'
            '<strong>字幕翻譯：漸進模式</strong>'
            '<span id="client-progressive-status">等待 master 播放後開始處理目前位置。</span>'
            '</div>'
        )
    elif progressive_requested:
        progressive_html = (
            '<div id="client-progressive-state" class="alignment-state manual">'
            '<strong>字幕翻譯：無法啟用</strong>'
            '<span>這支影片目前沒有可供逐段翻譯使用的字幕時間軸。</span>'
            '</div>'
        )

    # 4174 never starts translation. Cached subtitle state is shown above.
    ab_translation_controls = ""

    quick = f"""
{alignment_html}
{progressive_html}
<div id="client-quick-controls">
  <button id="client-pause" type="button">同步暫停</button>
  <button id="client-catchup" type="button">重新對齊</button>
  {ab_translation_controls}
  <span class="spacer"></span>
  <button id="client-immersive" class="immersive" type="button">沉浸全螢幕</button>
</div>
{cue_details}
"""
    if '<div id="layout-controls">' in inner:
        inner = inner.replace('<div id="layout-controls">', quick + '<div id="layout-controls">', 1)

    controls_open = '<div id="controls">'
    if controls_open in inner:
        inner = inner.replace(
            controls_open,
            '<details id="client-advanced"><summary>進階同步設定</summary><div id="controls">',
            1,
        )
        inner = inner.replace(
            '</div><script>',
            '</div></details><script>',
            1,
        )

    proxy_js = r"""
<script>
(function(){
  const click=(id)=>{const target=document.getElementById(id);if(target)target.click();};
  const pause=document.getElementById('client-pause');if(pause)pause.onclick=()=>click('pause-both');
  const catchup=document.getElementById('client-catchup');if(catchup)catchup.onclick=()=>click('catchup');
  const immersive=document.getElementById('client-immersive');
  function scrollInnerPttToLatest(){
    const frame=document.querySelector('.viewer-frame iframe');
    try{
      const inner=frame?.contentDocument;
      const feed=inner?.getElementById('ptt-feed');
      const follow=inner?.getElementById('ptt-follow');
      if(feed&&(!follow||follow.checked))feed.scrollTop=feed.scrollHeight;
    }catch(_){}
  }
  if(immersive)immersive.onclick=async()=>{
    try{
      if(!document.fullscreenElement)await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    }catch(_){}
  };
  document.addEventListener('fullscreenchange',()=>{
    document.body.classList.toggle('client-immersive',Boolean(document.fullscreenElement));
    if(immersive)immersive.textContent=document.fullscreenElement?'退出沉浸':'沉浸全螢幕';
    if(document.fullscreenElement){
      requestAnimationFrame(()=>requestAnimationFrame(scrollInnerPttToLatest));
      setTimeout(scrollInnerPttToLatest,250);
    }
  });
})();
</script>
"""
    proxy_js = proxy_js.replace("__MASTER_VIDEO_ID__", json.dumps(master_video_id))
    return inner.replace("</body></html>", proxy_js + "</body></html>", 1)


def backend_style_alignment(transcript_text: str) -> ClientWatchalongAlignment:
    """Match the accepted Streamlit transcript/cue pipeline and retain diagnostics."""

    if not transcript_text.strip():
        return ClientWatchalongAlignment(False, 0, (), (), (), "none", 0, 0, ())
    parsed = parse_manual_transcript(transcript_text)
    raw_cues = infer_watchalong_cues(parsed.segments)
    starts: list[float] = []
    for cue in confirmed_episode_start_cues(raw_cues):
        seconds = cue.start_ms / 1000.0
        if not starts or seconds - starts[-1] >= 20:
            starts.append(seconds)
    cues = tuple(
        ClientWatchalongCue(
            time_ms=cue.start_ms,
            kind=cue.kind,
            confidence=cue.confidence,
            text=cue.text,
            reason=cue.reason,
        )
        for cue in raw_cues
    )
    return ClientWatchalongAlignment(
        True,
        len(parsed.segments),
        tuple(starts),
        cues,
        subtitle_payload(parsed.segments),
        "none",
        0,
        len(parsed.segments),
        (),
    )


def backend_style_episode_starts(transcript_text: str) -> tuple[float, ...]:
    """Compatibility wrapper for backend-parity start points."""

    return backend_style_alignment(transcript_text).starts



def load_client_cached_ab_translation(video: str) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """Read the exact cached 8501 A/B quality tracks; never start provider work."""

    video_id = parse_youtube_video_id(video)
    if not video_id:
        return (), ()
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    corpus = TranscriptCorpus(client_runtime_root() / "data" / "watchalong" / "transcripts")
    try:
        from archive_translation_service import ArchiveTranslationService
        from translation_quality_existing_adapter import inspect_existing
        quality = inspect_existing(canonical, service=ArchiveTranslationService(corpus))
    except (ValueError, KeyError, OSError, TypeError):
        return (), ()
    if not quality.get("a_cached"):
        return (), ()
    ja = tuple(quality.get("ja", ()))
    a = tuple(quality.get("a", ()))
    if not ja or not a or len(ja) != len(a):
        return (), ()
    a_subtitles = tuple({
        "start": row["start_ms"] / 1000.0,
        "end": row["end_ms"] / 1000.0,
        "text": ja[i]["text"],
        "translated": row["text"],
    } for i, row in enumerate(a))
    b_subtitles = ()
    try:
        from translation_fansub_capture import private_capture_root
        from translation_quality_b_long_job import (
            job_fingerprint, nonoverlap_source, progress, verify_complete_b,
        )
        from translation_sentence_reconstruction import SourceCue, reconstruct_sentences
        fingerprint = job_fingerprint(ja, video_id=video_id, a=a)
        folder = private_capture_root().parent / "b-long-jobs"
        units = reconstruct_sentences(tuple(
            SourceCue(str(i), row["start_ms"], row["end_ms"], row["text"])
            for i, row in enumerate(nonoverlap_source(ja))
        ))
        state = progress(folder, fingerprint=fingerprint, total=len(units.sentences))
        if state["total"] > 0 and state["completed"] == state["total"] and not state["blocked"]:
            verified = verify_complete_b(ja, a, video_id=video_id, folder=folder)
            b_subtitles = tuple({
                "start": max(0.0, cue.start_ms / 1000.0),
                "end": max(0.0, cue.end_ms / 1000.0),
                "text": "",
                "translated": cue.text,
            } for cue in verified)
    except (ValueError, KeyError, OSError, TypeError):
        b_subtitles = ()
    return a_subtitles, b_subtitles


def resolve_watchalong_alignment(master: str) -> ClientWatchalongAlignment:
    """Reuse backend transcript/cue logic and any already-saved translation artifact."""

    master_id = parse_youtube_video_id(master)
    if not master_id:
        return ClientWatchalongAlignment(False, 0, (), (), (), "none", 0, 0, transcript_issue="影片識別碼無法辨識。")
    canonical_master = f"https://www.youtube.com/watch?v={master_id}"
    root = client_runtime_root()
    corpus = TranscriptCorpus(root / "data" / "watchalong" / "transcripts")
    service = TranscriptIngestService(corpus)
    archive_path = root / "data" / "watchalong" / "watchalong_archive.sqlite3"
    try:
        loaded = load_watchalong_transcript(
            canonical_master,
            archive_path=archive_path,
            corpus=corpus,
            ingest_service=service,
            read_only=True,
        )
    except Exception as exc:
        # Preserve a safe diagnostic instead of hiding read failures as missing captions.
        return ClientWatchalongAlignment(
            False, 0, (), (), (), "none", 0, 0,
            transcript_issue=f"Transcript 讀取失敗（{type(exc).__name__}）。請確認 8501 的字幕已儲存至共用資料庫。",
        )

    report = backend_style_alignment(loaded.transcript_text)
    if not report.transcript_available:
        public = getattr(loaded, "public_outcome", None)
        if public is not None and not public.available:
            # Share the backend acquisition result; do not report it as a local read error.
            return ClientWatchalongAlignment(
                False, 0, (), (), (), "none", 0, 0,
                transcript_issue="共用字幕庫尚無此影片的 Transcript；8501 公開字幕取得流程也未取得可用內容。若 ASR 排程尚未完成，請稍後重試。",
            )
    record = getattr(loaded, "record", None)
    if record is None:
        return report

    progressive_segments = tuple(
        TranscriptSegment(
            item.start_ms,
            item.end_ms,
            item.source_text,
            provider=record.source_type,
        )
        for item in record.segments
    )
    report = ClientWatchalongAlignment(
        report.transcript_available,
        report.segment_count,
        report.starts,
        report.cues,
        report.subtitles,
        report.translation_status,
        report.translated_segments,
        report.translation_total_segments,
        progressive_segments,
    )

    # 4174 is read-only: load only artifacts already produced by 8501.
    a_subtitles, b_subtitles = load_client_cached_ab_translation(master_id)
    if not a_subtitles and not b_subtitles:
        return report
    primary_subtitles = a_subtitles if a_subtitles else b_subtitles
    translation_total = max(len(a_subtitles), len(b_subtitles))
    translated_count = sum(
        1 for item in primary_subtitles if str(item.get("translated", "")).strip()
    )
    status = "ready" if translation_total and translated_count >= translation_total else "partial"
    return ClientWatchalongAlignment(
        report.transcript_available,
        report.segment_count,
        report.starts,
        report.cues,
        a_subtitles,
        status,
        translated_count,
        translation_total,
        progressive_segments,
        a_subtitles=a_subtitles,
        b_subtitles=b_subtitles,
    )


def resolve_watchalong_episode_starts(
    master: str,
    source_count: int | None = None,
) -> tuple[float, ...]:
    """Compatibility wrapper over the full backend-parity alignment report."""

    if source_count is not None and source_count <= 0:
        return ()
    starts = resolve_watchalong_alignment(master).starts
    return starts if source_count is None else starts[:source_count]


def load_client_watchalong_ptt(master: str) -> WatchalongPttPayload:
    """Reuse the backend read-only PTT timeline loader for the Client."""

    master_id = parse_youtube_video_id(master)
    if not master_id:
        return WatchalongPttPayload((), "")
    try:
        return load_watchalong_ptt_messages(master_id)
    except Exception:
        return WatchalongPttPayload((), "")


def resolve_watchalong_master_mode(master: str) -> str:
    """Match the backend auto mode decision: archive / live / unknown."""

    master_id = parse_youtube_video_id(master)
    if not master_id:
        raise ValueError("Hololive 主影片無法辨識，請確認 YouTube URL 或 Video ID。")
    # A verified ended stream never becomes live again; use the persisted
    # catalog before making a remote YouTube API call. In-progress entries can
    # be stale, so they must still be checked against the provider.
    try:
        from client_stream_catalog import load_client_catalog_video
        saved = load_client_catalog_video(client_runtime_root(), master_id)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        saved = None
    if saved is not None and saved.lifecycle_state == "ended" and saved.actual_end is not None:
        return "archive"
    video = fetch_video(master_id, load_api_key())
    if video.completed:
        return "archive"
    if video.live_state in {"live", "upcoming"} or video.actual_start is not None:
        return "live"
    return "unknown"


def build_watchalong_session_html(
    master: str,
    source: str = "",
    *,
    source_urls: Iterable[str] | None = None,
    episode_master_starts: Iterable[float] = (),
    live_queue_standby: bool = False,
    alignment: ClientWatchalongAlignment | None = None,
    ptt_messages: Iterable[dict] = (),
    telemetry: ClientWatchalongTelemetry | None = None,
    progressive_enabled: bool = False,
    progressive_requested: bool = False,
    ab_translation_enabled: bool = False,
) -> str:
    """Render embedded YouTube Watchalong, including an optional source queue."""

    sources = tuple(source_urls or ((source,) if source else ()))
    starts = tuple(float(value) for value in episode_master_starts)
    session = watchalong_session_from_inputs(
        master,
        sources,
        episode_master_starts=starts,
        archive_auto_lock=bool(starts),
        live_queue_standby=live_queue_standby,
        telemetry_endpoint="",
        telemetry_token="",
        telemetry_session_id="",
    )
    inner = render_watchalong_session(session)
    inner = enhance_watchalong_html(
        inner,
        subtitles=(alignment.subtitles if alignment is not None else ()),
        a_subtitles=(getattr(alignment, "a_subtitles", ()) if alignment is not None else ()),
        b_subtitles=(getattr(alignment, "b_subtitles", ()) if alignment is not None else ()),
        ptt_messages=tuple(ptt_messages),
        subtitle_feed_url="",
        subtitle_feed_token="",
        subtitle_feed_session_id="",
    )
    inner = _clientize_watchalong_inner(
        inner,
        episode_starts=starts,
        source_count=len(sources),
        alignment_report=alignment,
        progressive_enabled=False,
        progressive_requested=False,
        progressive_session_id="",
        progressive_token="",
        master_video_id=session.master.video_id,
        ab_translation_enabled=ab_translation_enabled,
        ab_translation_ready=bool(
            getattr(alignment, "a_subtitles", ()) or getattr(alignment, "b_subtitles", ())
        ) if alignment is not None else False,
    )
    return client_viewer_document(
        title="同時視聽",
        active="watchalong",
        inner_html=inner,
        back_href="/watchalong",
        back_label="← 返回同時視聽",
        inner_css=WATCHALONG_INNER_CSS,
        wide=True,
    )


def build_companion_session_html(master: str, external_source: str) -> str:
    """Render the existing companion flow for non-YouTube providers."""

    master_id = parse_youtube_video_id(master)
    if not master_id:
        raise ValueError("Hololive 主影片無法辨識，請確認 YouTube URL 或 Video ID。")
    if not is_http_source(external_source):
        raise ValueError("外部片源網址無法辨識，請提供 http(s) 網址。")
    provider = detect_provider(external_source)
    inner = build_companion_watchalong_html(
        master_video_id=master_id,
        provider_label=provider.label,
    )
    placeholder_css = r"""
#side:before{content:"🐰 外部片源預留區";display:grid;place-items:center;min-height:150px;border:1px dashed #4a4a4a;border-radius:12px;background:#161616;color:#aaa;font-size:15px;font-weight:800;margin-bottom:2px}
"""
    return client_viewer_document(
        title=f"同時視聽 · {provider.label}",
        active="watchalong",
        inner_html=inner,
        back_href="/watchalong",
        back_label="返回同時視聽",
        inner_css=WATCHALONG_INNER_CSS + placeholder_css,
        wide=True,
    )
