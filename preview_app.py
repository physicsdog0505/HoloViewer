"""Isolated Streamlit entrypoint for pre-reviewed static exact Client HTML only."""
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="HoloViewer · Client UI comparison", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
header[data-testid="stHeader"]{display:none}
[data-testid="stMainBlockContainer"]{max-width:100%;padding:0}
[data-testid="stSidebar"]{display:none}
</style>""", unsafe_allow_html=True)

fixture = Path(__file__).resolve().parent / "client_exact_preview.html"
if not fixture.is_file():
    st.warning("真正 Client Renderer 的已審查 HTML 尚未放入這個預覽分支；不使用早期 Wireframe 代替。")
    st.stop()

html = fixture.read_text(encoding="utf-8")
if not html.startswith("<!doctype html>"):
    st.error("預覽檔案格式不符，已停止載入。")
    st.stop()
st.components.v1.html(html, height=1600, scrolling=True)
