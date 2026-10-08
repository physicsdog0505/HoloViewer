"""Static visual-only comparison container, no private runtime or DB imports."""
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="HoloViewer · Client UI comparison",layout="wide",initial_sidebar_state="collapsed")
st.markdown("""<style>header[data-testid="stHeader"]{display:none}
[data-testid="stMainBlockContainer"]{max-width:100%;padding:0}
[data-testid="stSidebar"]{display:none}</style>""",unsafe_allow_html=True)

artifact = Path(__file__).resolve().parent / "client_exact_preview.html"
if not artifact.is_file():
    st.warning("真正 Client Renderer 的靜態預覽尚未發布到此分支；不以舊 Wireframe 替代。")
    st.stop()

html = artifact.read_text(encoding="utf-8")
if not html.startswith("<!doctype html>"):
    st.error("預覽 HTML 格式錯誤，已停止載入。")
    st.stop()

st.components.v1.html(html, height=1500, scrolling=True)
