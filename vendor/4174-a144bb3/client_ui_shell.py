"""Shared visual shell for the standalone Client UI."""

from __future__ import annotations

from html import escape


NAV_ITEMS = (
    ("home", "/", "今", "今日直播"),
    ("history", "/history", "史", "歷史直播"),
    ("watchalong", "/watchalong", "視", "同時視聽"),
    ("custom", "/custom-view", "自", "自訂觀看"),
    ("collab", "/collab", "👥", "多人連動"),
    ("ptt", "/ptt-today", "PTT", "PTT 今日專串"),
)


CLIENT_CSS = r"""
:root{
  color-scheme:light;
  --bg:#f7f5f2;--surface:#fffdfa;--surface-2:#f1efeb;--text:#242321;--muted:#77736c;
  --line:#e6e1da;--accent:#6faec9;--accent-soft:#e5f2f7;--danger:#c85d67;
  --shadow:0 10px 30px rgba(52,44,36,.08);--content:1240px;--rail-collapsed:72px;--rail-expanded:250px;--brand-main:#A65788;--brand-soft:#B8A6D8;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);font-family:Inter,"Noto Sans TC","PingFang TC",system-ui,-apple-system,sans-serif}
a{color:inherit;text-decoration:none}
button,input,select{font:inherit}
.client-rail{position:fixed;left:0;top:0;bottom:0;z-index:60;width:var(--rail-collapsed);padding:12px 8px;background:rgba(255,253,250,.97);backdrop-filter:blur(18px);border-right:1px solid var(--line);transition:width .18s ease;overflow:hidden}
.client-rail:hover,.client-rail:focus-within{width:var(--rail-expanded);box-shadow:10px 0 28px rgba(52,44,36,.08)}
.rail-brand,.rail-nav a{display:grid;grid-template-columns:54px minmax(0,1fr);align-items:center;column-gap:10px;height:44px;border-radius:12px;white-space:nowrap;padding:0 1px}
.rail-brand{margin-bottom:18px;font-weight:800;color:var(--brand-main);font-size:17px}.rail-brand .rail-icon{font-size:23px;line-height:1;color:var(--brand-main);font-weight:900}.rail-brand .rail-label{display:flex;align-items:center;min-height:44px;font-size:19px;line-height:1;letter-spacing:-.025em;color:var(--brand-main)}
.rail-nav{display:grid;gap:6px}
.rail-nav a{color:var(--muted)}
.rail-nav a:hover,.rail-nav a.active{background:var(--surface-2);color:var(--text)}
.rail-icon{width:54px;min-width:54px;height:44px;display:grid;place-items:center;text-align:center;font-size:16px;font-weight:800}\n.rail-nav a[href="/collab"] .rail-icon{font-size:27px;font-weight:900;line-height:1;color:#20252a}
.rail-label{font-size:16px;font-weight:700;opacity:0;transform:translateX(-6px);transition:.16s ease}
.client-rail:hover .rail-label,.client-rail:focus-within .rail-label{opacity:1;transform:none}
.client-topbar{position:sticky;top:0;z-index:30;height:58px;margin-left:var(--rail-collapsed);display:flex;justify-content:flex-end;align-items:center;padding:0 24px;background:rgba(247,245,242,.9);backdrop-filter:blur(16px);border-bottom:1px solid rgba(230,225,218,.8);transition:margin-left .18s ease}
.top-brand{display:none}.mobile-top-brand{display:none}
.top-status{margin-left:auto;color:#856C86;font-size:13px;font-weight:800;letter-spacing:.065em;background:transparent;border:0;border-radius:0;padding:6px 0}.top-status:empty{display:none}
.mobile-nav-button{display:none}
.mobile-nav{display:none}
.client-main{max-width:calc(var(--content) + var(--rail-collapsed));margin:0 auto;padding:24px 24px 80px calc(24px + var(--rail-collapsed));transition:padding-left .18s ease,max-width .18s ease}
.page-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:26px}
.page-head h1{margin:0 0 8px;font-size:34px;letter-spacing:-.035em}
.page-head p{margin:0;color:var(--muted);line-height:1.65}
.eyebrow{font-size:11px;font-weight:800;letter-spacing:.11em;color:#4f7f93;text-transform:uppercase}
.section{margin:34px 0 46px}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:15px}
.section-head h2{margin:0;font-size:22px}
.section-head p{margin:5px 0 0;color:var(--muted);font-size:13px}
.surface{background:var(--surface);border:1px solid var(--line);border-radius:18px;box-shadow:0 1px 0 rgba(52,44,36,.02)}
.primary-action,.subtle-action{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 16px;border-radius:12px;border:1px solid var(--line);background:var(--surface);cursor:pointer;font-weight:700}
.primary-action{background:var(--text);color:#fff;border-color:var(--text)}
.subtle-action:hover{background:var(--surface-2)}
.form-error{margin:0 0 14px;padding:10px 12px;border-radius:12px;background:#fff0ed;color:#9b3528;border:1px solid #f2d3cd}
.empty-note{color:var(--muted);font-size:13px;line-height:1.65}
.client-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px 18px}
.client-card{display:block;min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;transition:transform .14s ease,border-color .14s ease,box-shadow .14s ease}
.client-card:hover,.client-card:focus-visible{transform:translateY(-2px);border-color:#cbdde4;box-shadow:0 8px 22px rgba(52,44,36,.06);outline:none}
.card-thumb{position:relative;aspect-ratio:16/9;background:linear-gradient(135deg,#cfdde3,#e8ddd5);overflow:hidden}
.card-thumb img{display:block;width:100%;height:100%;object-fit:cover}
.youtube-source-link{position:absolute;right:8px;top:8px;z-index:8;display:inline-flex;align-items:center;justify-content:center;min-height:26px;padding:3px 8px;border:1px solid rgba(255,255,255,.48);border-radius:999px;background:rgba(15,15,15,.76);color:#fff;font-size:10px;font-weight:800;line-height:1;cursor:pointer;backdrop-filter:blur(5px);box-shadow:0 2px 7px rgba(0,0,0,.16)}
.youtube-source-link:hover,.youtube-source-link:focus-visible{background:#fff;color:#111;border-color:#fff;outline:none}
.card-copy{padding:12px 13px 14px}
.card-copy h3{font-size:14px;line-height:1.48;margin:7px 0 4px}
.card-copy p{margin:0;color:var(--muted);font-size:12px;line-height:1.5}
.status-pill{display:inline-flex;align-items:center;min-height:22px;padding:0 7px;border-radius:999px;font-size:10px;font-weight:800;background:var(--surface-2);color:#625e58}
.status-pill.live{background:#ffe5e8;color:#c94450}
.status-pill.upcoming{background:#fff3d9;color:#8e6500}
.status-pill.ended{background:#eeece9;color:#706b64}
.card-meta{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:11px;margin-top:6px}
.feature-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.feature-card{padding:20px;min-height:126px;border:1px solid var(--line);border-radius:18px;background:var(--surface);display:flex;flex-direction:column;justify-content:space-between}
.feature-card strong{font-size:18px}.feature-card span{margin-top:8px;color:var(--muted);font-size:13px;line-height:1.55}
.tool-card{padding:20px;border:1px solid var(--line);border-radius:18px;background:var(--surface)}
input,select{width:100%;border:1px solid #d8d3cc;border-radius:11px;padding:11px 12px;background:white;color:var(--text)}
input:focus,select:focus{outline:2px solid #cfe4ed;border-color:#9fc7d7}
.viewer-shell{display:grid;gap:14px}
.viewer-head{display:flex;align-items:center;justify-content:space-between;gap:14px}
.viewer-head h1{margin:0;font-size:25px;letter-spacing:-.025em}
.viewer-frame{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:#0b0b0b;box-shadow:var(--shadow)}
.viewer-frame iframe{display:block;width:100%;height:calc(100vh - 132px);min-height:680px;border:0;background:#0b0b0b}
body.viewer-wide .client-main{max-width:none;padding-right:18px}
body.viewer-wide .viewer-shell{width:100%}
body.viewer-wide .viewer-frame iframe{height:calc(100vh - 126px);min-height:720px}
@media (min-width:761px){
  body:has(.client-rail:hover) .client-topbar,body:has(.client-rail:focus-within) .client-topbar{margin-left:var(--rail-expanded)}
  body:has(.client-rail:hover) .client-main,body:has(.client-rail:focus-within) .client-main{padding-left:calc(24px + var(--rail-expanded));max-width:calc(var(--content) + var(--rail-expanded))}
}
@media(max-width:1040px){.client-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.feature-row{grid-template-columns:1fr}}
@media(max-width:760px){
  .client-rail{display:none}.client-topbar{margin-left:0;padding:0 16px;justify-content:space-between}.mobile-nav-button{display:block;border:1px solid var(--line);background:var(--surface);border-radius:10px;width:38px;height:38px}
  .mobile-top-brand{display:block;color:var(--brand-main);font-weight:900;font-size:18px;margin-left:12px}.mobile-nav{position:fixed;z-index:70;left:12px;right:12px;top:64px;padding:10px;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);display:grid;gap:4px}
  .mobile-nav[hidden]{display:none}.mobile-nav a{padding:11px 12px;border-radius:10px}.mobile-nav a.active,.mobile-nav a:hover{background:var(--surface-2)}
  .client-main{padding:26px 16px 72px}.page-head{align-items:start;flex-direction:column}.page-head h1{font-size:29px}.client-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 12px}
  .viewer-frame iframe{height:calc(100vh - 130px);min-height:520px}
}
@media(max-width:480px){.client-grid{grid-template-columns:1fr}.top-brand{font-size:16px}}
"""


LIVE_RAIL_CSS = r""".live-channel-rail{
  position:fixed;left:2px;top:270px;z-index:65;width:64px;max-height:calc(100vh - 282px);
  display:flex;flex-direction:column;gap:8px;padding:8px 0;overflow-x:hidden;overflow-y:auto;
  background:rgba(255,253,250,.98);border-radius:14px;scrollbar-width:none;
  transition:width .16s ease,box-shadow .16s ease
}
.live-channel-rail::-webkit-scrollbar{display:none}
.live-channel-label{display:none;padding:2px 10px 5px;color:var(--muted);font-size:11px;font-weight:800;white-space:nowrap}
.live-channel-rail:hover,.live-channel-rail:focus-within{width:222px;box-shadow:8px 8px 24px rgba(52,44,36,.09)}
.live-channel-rail:hover .live-channel-label,.live-channel-rail:focus-within .live-channel-label{display:block}
.live-channel-rail-item{display:grid;grid-template-columns:52px minmax(0,1fr);align-items:center;gap:8px;min-height:56px;padding:2px 4px;border-radius:10px;color:var(--member-accent,var(--text));font-size:12px}
.live-channel-rail-item:hover,.live-channel-rail-item:focus-visible{background:color-mix(in srgb,var(--member-accent,#7aa8bb) 7%,white);outline:none}
.live-channel-rail-item[hidden]{display:none!important}
.live-channel-rail-item strong{opacity:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700;color:color-mix(in srgb,var(--member-accent,var(--text)) 62%,#25232a)}
.live-channel-rail:hover .live-channel-rail-item strong,.live-channel-rail:focus-within .live-channel-rail-item strong{opacity:1}
.live-channel-avatar{position:relative;width:52px;height:52px;flex:0 0 52px;border-radius:50%;display:grid;place-items:center;background:white;border:2px solid var(--member-accent,#9ab8c4);color:var(--member-accent,#4f7f93);font-size:9px;font-weight:800}
.live-channel-avatar img,.live-channel-avatar>span{width:100%;height:100%;border-radius:50%;object-fit:cover;display:grid;place-items:center;overflow:hidden}
.live-channel-avatar i{position:absolute;right:-2px;bottom:-1px;width:10px;height:10px;border-radius:50%;background:#e6213c;border:2px solid white}
@media(min-width:761px){
  body:has(.client-rail:hover) .live-channel-rail,body:has(.client-rail:focus-within) .live-channel-rail{width:222px}
  body:has(.client-rail:hover) .live-channel-rail-item strong,body:has(.client-rail:focus-within) .live-channel-rail-item strong{opacity:1}
  body:has(.client-rail:hover) .live-channel-label,body:has(.client-rail:focus-within) .live-channel-label{display:block}
}
@media(max-width:760px){.live-channel-rail{display:none}}
[data-support-mode="dual_color"] .live-channel-avatar{background:var(--member-accent-dual)!important;border-color:transparent!important;padding:3px}
"""

CLIENT_JS = r"""
const mobileNavButton=document.getElementById('mobileNavButton');
// Share Today's category selection across every 4174 page and browser tab.
const LIVE_FILTER_KEY='holoviewer-live-filter';
const LIVE_FILTER_VALUES=new Set(['hololive','holostars','mekpark','all']);
function readLiveFilter(){
  try{
    const saved=localStorage.getItem(LIVE_FILTER_KEY);
    return LIVE_FILTER_VALUES.has(saved)?saved:'hololive';
  }catch(_error){return 'hololive';}
}
function syncLiveRailFilter(filter=readLiveFilter()){
  document.querySelectorAll('.live-channel-rail-item').forEach(item=>{
    item.hidden=filter!=='all'&&item.dataset.group!==filter;
  });
}
window.holoviewerLiveFilter={read:readLiveFilter,set(filter){
  if(!LIVE_FILTER_VALUES.has(filter))return;
  try{localStorage.setItem(LIVE_FILTER_KEY,filter);}catch(_error){}
  syncLiveRailFilter(filter);
},sync:syncLiveRailFilter};
window.addEventListener('storage',event=>{
  if(event.key===LIVE_FILTER_KEY)syncLiveRailFilter();
});
syncLiveRailFilter();

document.addEventListener('click',event=>{
  const source=event.target.closest('[data-youtube-href]');
  if(!source)return;
  event.preventDefault();event.stopPropagation();
  const href=source.dataset.youtubeHref;
  if(href)window.open(href,'_blank','noopener,noreferrer');
});
document.addEventListener('keydown',event=>{
  const source=event.target.closest('[data-youtube-href]');
  if(!source||(event.key!=='Enter'&&event.key!==' '))return;
  event.preventDefault();event.stopPropagation();
  const href=source.dataset.youtubeHref;
  if(href)window.open(href,'_blank','noopener,noreferrer');
});

const mobileNav=document.getElementById('mobileNav');
if(mobileNavButton&&mobileNav){
  mobileNavButton.addEventListener('click',()=>{
    const opening=mobileNav.hidden;
    mobileNav.hidden=!opening;
    mobileNavButton.setAttribute('aria-expanded',String(opening));
  });
  mobileNav.addEventListener('click',()=>{
    mobileNav.hidden=true;
    mobileNavButton.setAttribute('aria-expanded','false');
  });
}
"""


def _nav_links(active: str, *, mobile: bool = False) -> str:
    links = []
    for key, href, icon, label in NAV_ITEMS:
        active_class = " active" if key == active else ""
        if mobile:
            links.append(f'<a class="{active_class.strip()}" href="{href}">{escape(label)}</a>')
        else:
            links.append(
                f'<a class="{active_class.strip()}" href="{href}">'
                f'<span class="rail-icon">{escape(icon)}</span>'
                f'<span class="rail-label">{escape(label)}</span></a>'
            )
    return "".join(links)


def client_document(
    *,
    title: str,
    active: str,
    content: str,
    extra_css: str = "",
    extra_script: str = "",
    top_status: str = "",
    body_class: str = "",
    live_rail_html: str | None = None,
) -> str:
    """Wrap one production Client page in the shared responsive shell."""

    status = escape(top_status) if top_status else ""
    # Resolve once per page request from the same persisted live catalog as Today.
    # Lazy import keeps client_home -> client_ui_shell dependencies acyclic.
    from client_home import _live_channel_rail, load_home_streams
    if live_rail_html is None:
        live, _, _, _ = load_home_streams()
        live_rail = _live_channel_rail(live)
    else:
        live_rail = live_rail_html
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | HoloViewer</title>
<style>{CLIENT_CSS}\n{LIVE_RAIL_CSS}\n{extra_css}</style>
</head>
<body class="{escape(body_class)}">
<aside class="client-rail" aria-label="主要功能">
  <a class="rail-brand" href="/" aria-label="HoloViewer 首頁"><span class="rail-icon">H</span><span class="rail-label">HoloViewer</span></a>
  <nav class="rail-nav">{_nav_links(active)}</nav>
</aside>
<header class="client-topbar">
  <button id="mobileNavButton" class="mobile-nav-button" type="button" aria-expanded="false" aria-controls="mobileNav" aria-label="開啟導覽">☰</button>
  <a class="mobile-top-brand" href="/">HoloViewer</a>
  <div class="top-status">{status}</div>
</header>
<div id="mobileNav" class="mobile-nav" hidden>{_nav_links(active, mobile=True)}</div>
{live_rail}
<main class="client-main">{content}</main>
<script>{CLIENT_JS}\n{extra_script}</script>
</body>
</html>"""



def client_viewer_document(
    *,
    title: str,
    active: str,
    inner_html: str,
    back_href: str,
    back_label: str,
    inner_css: str = "",
    wide: bool = False,
) -> str:
    """Frame an existing verified full-document renderer in Client chrome.

    Optional CSS is presentation-only and is injected before the renderer's first
    closing style tag. The renderer's JavaScript and player lifecycle stay intact.
    """

    themed = inner_html
    if inner_css and "</style>" in themed:
        themed = themed.replace("</style>", inner_css + "\n</style>", 1)
    srcdoc = escape(themed, quote=True)
    content = (
        '<div class="viewer-shell">'
        '<div class="viewer-head">'
        f'<h1>{escape(title)}</h1>'
        f'<a class="subtle-action" href="{escape(back_href, quote=True)}">{escape(back_label)}</a>'
        "</div>"
        '<div class="viewer-frame">'
        f'<iframe title="{escape(title, quote=True)}" srcdoc="{srcdoc}" allow="autoplay; fullscreen" allowfullscreen></iframe>'
        "</div></div>"
    )
    return client_document(
        title=title,
        active=active,
        content=content,
        body_class="viewer-wide" if wide else "",
    )
