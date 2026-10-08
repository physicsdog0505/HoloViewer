"""HoloViewer private staging entrypoint. No internal service imports."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="HoloViewer — Private staging", page_icon="📺", layout="wide")
st.title("HoloViewer")
st.caption("Unofficial fan project · Private staging · Not affiliated with COVER Corp. or YouTube.")
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
    st.info("此功能尚未完成獨立公開版驗收；Staging 暫不提供播放器。")
with tabs[2]:
    st.subheader("同時視聽")
    st.info("此功能尚未完成授權及公開版驗收；Staging 暫不提供播放器。")
st.caption("Private staging only. No PTT credentials, Collector or Admin available.")
