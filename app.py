"""HoloViewer public deployment smoke preview. No internal service imports."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="HoloViewer — Preview", page_icon="📺", layout="wide")
st.title("HoloViewer")
st.caption("Unofficial fan project · Public preview · Not affiliated with COVER Corp. or YouTube.")
st.info("Deployment preview only. Live data and playback pages are not connected or enabled yet.")
tabs = st.tabs(["首頁", "直播同步", "同時視聽"])
with tabs[0]:
    st.subheader("今日直播")
    snapshot, warning = load_snapshot(ROOT / "published_snapshot.json")
    if warning:
        st.info("公開直播資料尚未就緒。")
        st.caption(warning)
    else:
        st.caption(f"資料更新：{snapshot['generated_at']} (UTC)")
        if not snapshot["streams"]:
            st.info("此版本沒有已發布的直播項目。")
        for stream in snapshot["streams"]:
            st.write(f"{stream['title']} · {stream['status']}")
            st.link_button("在 YouTube 觀看", f"https://www.youtube.com/watch?v={stream['video_id']}")
with tabs[1]:
    st.subheader("直播同步")
    st.info("公開預覽版尚未開放此功能。")
with tabs[2]:
    st.subheader("同時視聽")
    st.info("公開預覽版尚未開放此功能。")
st.caption("Public deployment smoke preview only — no live PTT data, credentials or administrative services.")
