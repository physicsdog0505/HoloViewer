from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_portrait_translation_panel_contract():
    html = (ROOT / "site/viewer/index.html").read_text()
    css = (ROOT / "site/assets/viewer-standalone.css").read_text()
    js = (ROOT / "site/assets/viewer-standalone.js").read_text()

    assert 'id="mobileSubtitlePanel"' in html
    assert html.index('id="mobileSubtitlePanel"') < html.index('class="ptt-heading"')
    assert 'id="mobileSubtitleControl"' in html
    assert 'id="mobileSubtitleSwitch"' in html
    assert html.index('id="pttShowFloor"') < html.index('id="mobileSubtitleSwitch"')
    assert 'id="mobileSubtitleToggle"' not in html
    assert "@media(max-width:760px) and (orientation:portrait)" in css
    assert ".viewer-local-subtitle-overlay{display:none!important}" in css
    assert ".mobile-subtitle-control[hidden]{display:none!important}" in css
    assert "-webkit-text-stroke:2px var(--subtitle-stroke-color,#111111)" in css
    assert "const mobilePortraitMedia=window.matchMedia('(max-width:760px) and (orientation:portrait)')" in js
    assert "holoviewer-mobile-subtitle-open" in js
    assert "mobileSubtitleSwitch?.addEventListener('change'" in js
    assert "viewerSubtitleColorForCue(cue)" in js
    assert "renderMobileSubtitlePanel()" in js


def test_portrait_translation_panel_keeps_landscape_isolated():
    css = (ROOT / "site/assets/viewer-standalone.css").read_text()

    portrait = css.index("@media(max-width:760px) and (orientation:portrait)")
    landscape = css.index("@media(max-width:900px) and (orientation:landscape)")
    assert portrait < landscape

    landscape_end = css.index(".viewer-local-subtitle-panel", landscape)
    landscape_block = css[landscape:landscape_end]
    assert "mobile-subtitle-panel" not in landscape_block
