#!/usr/bin/env python3
"""Compare interactive custom-view browser state against accepted 4174."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

def scenario(browser, root, width):
    context = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    try:
        page.goto(root.rstrip("/") + "/custom-view", wait_until="domcontentloaded")
        for video in ("dQw4w9WgXcQ", "9bZkp7q19f0"):
            page.locator("#url").fill(video)
            page.locator("#add").click()
        added = page.evaluate("""() => ({
            selected: [...document.querySelectorAll('.selected-item')].map(e => e.dataset.video),
            count: document.querySelector('#selectedCount').textContent,
            layoutHidden: document.querySelector('#layoutControl').hidden,
            audioOptions: document.querySelector('#audio').options.length
        })""")
        assert len(added["selected"]) == 2, "adding videos failed"
        page.locator(".selected-item .item-actions button[title='往前']").nth(1).click()
        reordered = page.locator(".selected-item").evaluate_all("e => e.map(x => x.dataset.video)")
        page.locator("input[name='mainVideo']").nth(1).check()
        page.locator("#audio").select_option("0")
        page.locator("#start").click()
        page.wait_for_url("**/custom-view/session?**", wait_until="domcontentloaded")
        url = urlsplit(page.url)
        q = parse_qs(url.query)
        session = {"path": url.path, "streams": q.get("stream", []),
                   "layout": q.get("layout", []), "primary": q.get("primary", []),
                   "audio": q.get("audio", []), "ptt": q.get("ptt", []),
                   "iframes": page.locator("iframe").count()}
        page.goto(root.rstrip("/") + "/custom-view", wait_until="domcontentloaded")
        page.locator("#url").fill("dQw4w9WgXcQ")
        page.locator("#add").click()
        page.locator(".selected-item .item-actions button[title='移除']").click()
        return {"width": width, "added": added, "reordered": reordered,
                "session": session, "removedCount": page.locator(".selected-item").count(),
                "emptyState": page.locator(".empty-selection").count(),
                "railVisible": page.locator(".client-rail").is_visible(),
                "mobileNavVisible": page.locator("#mobileNavButton").is_visible()}
    finally:
        context.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--output", default="provenance/4174-browser-state-parity-receipt.json")
    args = p.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright not installed; run python3 -m pip install playwright && python3 -m playwright install chromium")
        return 2
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for width in (1440, 390):
                try:
                    baseline = scenario(browser, args.baseline, width)
                    candidate = scenario(browser, args.candidate, width)
                    passed = baseline == candidate
                    rows.append({"width": width, "pass": passed, "baseline": baseline, "candidate": candidate})
                    print(f"{'PASS' if passed else 'FAIL'}: custom-view browser-state {width}px")
                except Exception as exc:
                    rows.append({"width": width, "pass": False, "error": str(exc)})
                    print(f"FAIL: custom-view browser-state {width}px: {exc}")
        finally:
            browser.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "rows": rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"receipt: {output}")
    return 0 if rows and all(x["pass"] for x in rows) else 1

if __name__ == "__main__":
    raise SystemExit(main())
