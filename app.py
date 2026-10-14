"""Functional, zero-credential public viewing preview.

Only official YouTube embeds and an optional validated published snapshot.
This is a deployable interface slice; PTT and catalogue updates still require
the separately reviewed outbound publisher / public API.
"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import streamlit as st

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def canonical_video_id(value: str) -> str | None:
    candidate = value.strip()
    if VIDEO_ID.fullmatch(candidate):
        return candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/live/", "/shorts/", "/embed/")):
            candidate = parsed.path.split("/")[2]
        else:
            return None
    else:
        return None
    return candidate if VIDEO_ID.fullmatch(candidate) else None


st.set_page_config(page_title="HoloViewer — Public Preview", page_icon="📺", layout="wide")
st.title("HoloViewer")
st.caption("非官方 Hololive 觀看工具 · Public interactive preview · 非 COVER / YouTube 官方產品")

if "primary_video" not in st.session_state:
    st.session_state.primary_video = ""
if "multi_videos" not in st.session_state:
    st.session_state.multi_videos = []

tabs = st.tabs(["首頁", "單人觀看", "多人同時觀看", "同時視聽", "PTT"])

with tabs[0]:
    st.subheader("今日直播 / 公開目錄")
    snapshot, warning = load_snapshot(ROOT / "published_snapshot.json")
    if warning:
        st.info("真實直播目錄尚未接上公開 Publisher；這裡不顯示假直播資料。")
        st.caption(warning)
    else:
        st.caption(f"公開資料時間：{snapshot['generated_at']} UTC")
        for stream in snapshot["streams"]:
            with st.container(border=True):
                st.write(f"**{stream['title']}** · {stream['status']}")
                if st.button("帶入單人播放器", key="single_" + stream["video_id"]):
                    st.session_state.primary_video = stream["video_id"]
                if st.button("加入多人畫面", key="multi_" + stream["video_id"]):
                    if stream["video_id"] not in st.session_state.multi_videos:
                        st.session_state.multi_videos.append(stream["video_id"])
                st.link_button("YouTube 原始頁面", f"https://www.youtube.com/watch?v={stream['video_id']}")

with tabs[1]:
    st.subheader("單人觀看")
    entry = st.text_input("YouTube 影片網址或 11 碼 ID", value=st.session_state.primary_video, key="single_input")
    if st.button("播放", key="single_play"):
        vid = canonical_video_id(entry)
        if vid is None:
            st.error("無法辨識 YouTube 影片 ID。")
        else:
            st.session_state.primary_video = vid
    if st.session_state.primary_video:
        st.video(f"https://www.youtube.com/watch?v={st.session_state.primary_video}")
        st.caption("使用 YouTube 原生播放器；本預覽尚未提供 PTT 時軸與沉浸模式。")
    else:
        st.info("貼上 YouTube 影片網址即可開始觀看。")

with tabs[2]:
    st.subheader("多人同時觀看")
    value = st.text_input("新增一個 YouTube 影片網址或 ID", key="multi_input")
    if st.button("加入畫面", key="multi_add"):
        vid = canonical_video_id(value)
        if vid is None:
            st.error("無法辨識 YouTube 影片 ID。")
        elif vid not in st.session_state.multi_videos:
            st.session_state.multi_videos.append(vid)
    if st.button("清空多人畫面", disabled=not st.session_state.multi_videos):
        st.session_state.multi_videos = []
    if not st.session_state.multi_videos:
        st.info("新增影片後會在同一頁以雙欄顯示。")
    else:
        for start in range(0, len(st.session_state.multi_videos), 2):
            columns = st.columns(2)
            for column, vid in zip(columns, st.session_state.multi_videos[start:start + 2]):
                with column:
                    st.video(f"https://www.youtube.com/watch?v={vid}")
                    if st.button("移除此畫面", key="rm_" + vid):
                        st.session_state.multi_videos.remove(vid)
                        st.rerun()
    st.caption("目前為可操作的多人播放器預覽，不宣稱已具備 4174 的同步控制或動態 POV 自動偵測。")

with tabs[3]:
    st.subheader("同時視聽")
    st.info("Watchalong 對齊、Playlist 與已完成字幕需要 Public 資料 API；尚未啟用，避免誤認為正式完成。")

with tabs[4]:
    st.subheader("PTT")
    st.info("PTT 即時及歷史資料需要唯讀 Cloudflare Worker；尚未接上，這裡不提供假的推文。")

st.divider()
st.caption("功能預覽：單人與手動多人 YouTube 播放。資料同步、PTT、Watchalong 和 4174 完整功能仍在整合中。")
