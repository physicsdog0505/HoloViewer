"""Isolated, fixture-only visual preview of the Client shell. No private runtime."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="HoloViewer — UI preview", page_icon="📺", layout="wide", initial_sidebar_state="collapsed")
st.markdown(
    """<style>
    [data-testid="stAppViewContainer"]{background:#f7f5f2}
    [data-testid="stMainBlockContainer"]{max-width:100%;padding:0}
    header[data-testid="stHeader"]{display:none}
    [data-testid="stSidebar"]{display:none}
    iframe{border:0!important}
    </style>""",
    unsafe_allow_html=True,
)

# No network, DB, streaming, runtime import or licensed artwork. These mock cards
# are deliberately NOT actual Hololive stream facts.
preview_html = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f7f5f2;--surface:#fffdfa;--surface2:#f1efeb;--text:#242321;--muted:#77736c;--line:#e6e1da;--accent:#6faec9;--rail:64px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,"Noto Sans TC","PingFang TC",system-ui,sans-serif}
a{color:inherit;text-decoration:none}button{font:inherit;cursor:pointer}
.rail{position:fixed;left:0;top:0;bottom:0;width:64px;z-index:10;overflow:hidden;padding:12px 8px;background:rgba(255,253,250,.98);border-right:1px solid var(--line);transition:width .18s}
.rail:hover,.rail:focus-within{width:210px;box-shadow:10px 0 28px #342c2414}.nav{display:flex;align-items:center;gap:12px;height:44px;border-radius:12px;white-space:nowrap;margin-bottom:6px}
.nav[aria-current="page"],.nav:hover{background:var(--surface2)}.glyph{min-width:46px;text-align:center;font-size:12px;font-weight:800}.name{font-size:14px;opacity:0;transition:opacity .15s}
.rail:hover .name,.rail:focus-within .name{opacity:1}.brand{margin-bottom:22px;font-weight:800}
.top{height:58px;position:sticky;top:0;z-index:2;background:#f7f5f2ee;border-bottom:1px solid var(--line);margin-left:64px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:750;color:var(--muted)}
.status{position:absolute;right:22px;font-size:12px;font-weight:400}
main{margin-left:64px;max-width:1400px;padding:34px 32px 100px}.head{display:flex;justify-content:space-between;align-items:end;gap:20px}.eyebrow{font-size:11px;color:#4f7f93;font-weight:800;letter-spacing:.11em}
h1{margin:5px 0;font-size:34px;letter-spacing:-.035em}p{color:var(--muted);font-size:13px;line-height:1.65}
.notice{padding:13px 17px;border-radius:12px;background:#e5f2f7;color:#426d81;font-size:13px;margin-top:24px}
section{margin-top:32px}h2{font-size:22px;margin:0 0 6px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-bottom:15px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}.card{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--surface);min-width:0}
.art{aspect-ratio:16/9;background:linear-gradient(135deg,#cfdde3,#e8ddd5);display:grid;place-items:center;color:#66808a;font-size:12px}.art.alt{background:linear-gradient(135deg,#e8d8e1,#dae5d9)}
.info{padding:13px}.tag{font-size:11px;color:#4f7f93;font-weight:700}.card h3{font-size:14px;margin:7px 0;line-height:1.5}.meta{font-size:12px;color:var(--muted)}
.empty{border:1px dashed #d6d0c9;border-radius:16px;padding:28px;color:var(--muted);background:#fffdfa;font-size:14px}
.page{display:none}.page.active{display:block}.small{font-size:12px;color:#9b968e}.tool{background:var(--surface);border:1px solid var(--line);padding:22px;border-radius:16px}
button{border:1px solid var(--line);border-radius:10px;background:#fffdfa;padding:10px 15px}.mobile-menu{display:none}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:26px 18px 90px}}
@media(max-width:580px){.rail{bottom:auto;width:100%;height:54px;display:flex;gap:4px;padding:4px;position:sticky;top:0;border-bottom:1px solid var(--line)}.rail:hover,.rail:focus-within{width:100%;box-shadow:none}.brand{display:none}.nav{height:44px;flex:1;justify-content:center;gap:3px}.glyph{min-width:unset}.name,.rail:hover .name{opacity:1;font-size:11px}.top{margin-left:0;height:46px}.status{right:9px;font-size:10px}main{margin-left:0;padding:20px 14px 80px}.grid{gap:10px}.head{display:block}h1{font-size:27px}.info{padding:9px}.card h3{font-size:12px}}
</style></head><body>
<nav class="rail">
<a class="nav brand" href="#" aria-label="HoloViewer"><span class="glyph">H</span><span class="name">HoloViewer</span></a>
<a class="nav" href="#home" data-page="home" aria-current="page"><span class="glyph">今</span><span class="name">今日</span></a>
<a class="nav" href="#watchalong" data-page="watchalong"><span class="glyph">視</span><span class="name">同時視聽</span></a>
<a class="nav" href="#custom" data-page="custom"><span class="glyph">自</span><span class="name">自訂觀看</span></a>
<a class="nav" href="#ptt" data-page="ptt"><span class="glyph">PTT</span><span class="name">PTT 今日專串</span></a>
</nav>
<div class="top">HoloViewer <span class="status">UI Preview · Fixture only</span></div>
<main>
<div class="page active" id="home"><header class="head"><div><span class="eyebrow">TODAY</span><h1>今日直播</h1><p>延續 Client 視覺語言的雲端預覽。下方卡片為純展示資料，並非真實直播。</p></div></header>
<div class="notice">設計預覽：不連接 Collector、直播狀態、YouTube 或 Content Catalog。所有卡片皆為示意。</div>
<section><div class="section-head"><div><h2>正在直播</h2><p>卡片網格、間距、字級與縮圖比例預覽</p></div><span class="small">DEMO</span></div>
<div class="grid">
<article class="card"><div class="art">16:9 示意縮圖</div><div class="info"><span class="tag">● 直播中 · DEMO</span><h3>示範直播標題 A</h3><div class="meta">範例頻道 · 非真實資料</div></div></article>
<article class="card"><div class="art alt">16:9 示意縮圖</div><div class="info"><span class="tag">● 直播中 · DEMO</span><h3>示範直播標題 B</h3><div class="meta">範例頻道 · 非真實資料</div></div></article>
<article class="card"><div class="art">16:9 示意縮圖</div><div class="info"><span class="tag">● 直播中 · DEMO</span><h3>示範直播標題 C</h3><div class="meta">範例頻道 · 非真實資料</div></div></article>
<article class="card"><div class="art alt">16:9 示意縮圖</div><div class="info"><span class="tag">● 直播中 · DEMO</span><h3>示範直播標題 D</h3><div class="meta">範例頻道 · 非真實資料</div></div></article>
</div></section>
<section><div class="section-head"><div><h2>即將開始</h2><p>首頁分類區塊與空狀態</p></div></div><div class="empty">尚無公開資料 · 待 Content Catalog 上線後接入</div></section></div>
<div class="page" id="watchalong"><span class="eyebrow">WATCHALONG</span><h1>同時視聽</h1><p>共用導覽和頁面容器先行移植；播放器、Playlist、字幕同步都尚未啟用。</p><div class="notice">本頁目前僅供視覺比較，不提供播放操作。</div><section><div class="section-head"><h2>最近同時視聽</h2></div><div class="empty">未接入資料／功能仍在私人開發分支驗收中</div></section><section><div class="tool"><h2>手動建立</h2><p>工具區外觀預留，尚未開放操作。</p><button disabled>建立同時視聽（未啟用）</button></div></section></div>
<div class="page" id="custom"><span class="eyebrow">CUSTOM VIEW</span><h1>自訂觀看</h1><p>視覺佈局預覽，播放器與音源控制尚未移植。</p><div class="notice">本頁目前僅供版面比較。</div><section><div class="tool"><h2>觀看清單</h2><p>未加入影片；暫時不提供新增、播放或同步。</p><button disabled>開始觀看（未啟用）</button></div></section></div>
<div class="page" id="ptt"><span class="eyebrow">PTT TODAY</span><h1>PTT 今日專串</h1><p>預留共用版面與 Focus 閱讀模式。沒有連接本機推文資料庫。</p><div class="notice">本頁目前僅供版面比較，不顯示真實推文。</div><section><div class="empty">目前沒有已發布的 PTT 專串資料</div></section></div>
<p class="small" style="margin-top:55px">Unofficial fan project · Public UI visual preview · No actual streams, user content, private databases or credentials.</p>
</main>
<script>
for(const a of document.querySelectorAll('[data-page]'))a.addEventListener('click',e=>{e.preventDefault();const id=a.dataset.page;for(const p of document.querySelectorAll('.page'))p.classList.toggle('active',p.id===id);for(const nav of document.querySelectorAll('[data-page]')){if(nav===a)nav.setAttribute('aria-current','page');else nav.removeAttribute('aria-current')}window.scrollTo(0,0)});
</script></body></html>"""
st.components.v1.html(preview_html, height=1400, scrolling=True)
