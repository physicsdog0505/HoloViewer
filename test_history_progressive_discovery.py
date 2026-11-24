from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_history_subtitle_discovery_ui_contract():
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
    js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'id="historySubtitleDiscovery"' in html
    assert '>中文字幕</button>' in html
    assert 'id="historySubtitleFilter"' not in html
    assert ".history-subtitle-discovery{" in css
    assert "linear-gradient" in css
    assert '-webkit-background-clip:text' in css
    assert '.history-subtitle-discovery[aria-pressed="true"]' in css
    assert "renderHistorySubtitleControls()" in js
    assert "HISTORY_SUBTITLE_DISCOVERY_PARAM='view'" in js
    assert "HISTORY_SUBTITLE_DISCOVERY_VALUE='subtitles'" in js


def test_history_search_progressively_expands_months():
    js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "const HISTORY_DISCOVERY_BATCH_SIZE=30;" in js
    assert "async function loadYoutubeHistoryDiscovery" in js
    assert "historyPublishedMonths(manifest).slice().sort().reverse()" in js
    assert "if(collected.length>=target)break" in js
    assert "historyDiscoveryTarget+=HISTORY_DISCOVERY_BATCH_SIZE" in js
    assert "historySearchSourceHasMore=Boolean(discoverySource&&data.has_more===true)" in js
    assert "new IntersectionObserver" in js
    assert "rootMargin:'600px 0px'" in js


def test_subtitle_discovery_uses_vod_month_index_before_history_month():
    js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "/data/subtitles/manifests/by-vod-month/" in js
    assert "async function loadVodSubtitleMonthIds(month)" in js
    assert "monthIds=await loadVodSubtitleMonthIds(month)" in js
    assert "if(!monthIds.size){scanned+=1;continue}" in js
    assert "rows=rows.filter(row=>monthIds.has(String(row?.video_id||'')))" in js


def test_subtitle_filter_is_contextual_to_search_intent():
    js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    start = js.index("function renderHistorySearchIntent")
    end = js.index("\nfunction historyChrome", start)
    block = js[start:end]
    assert "history-subtitle-filter" in block
    assert "historySubtitleConstraintEnabled()" in block
    assert "historySubtitleFilterEnabled=!historySubtitleFilterEnabled" in block
    assert "box.append(subtitle)" in block
