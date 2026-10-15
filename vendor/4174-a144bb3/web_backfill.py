"""Import a complete PTT article from a public Web mirror without BBS login.

The first version deliberately writes to separate ``web_articles`` and
``web_pushes`` tables.  It never modifies the collector's ``articles`` or
``pushes`` tables, so Web data can be audited before any future merge.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sqlite3
import time
from typing import Iterable, Sequence
from urllib.parse import quote, urlparse


PTTWEB_HOSTS = {"pttweb.cc", "www.pttweb.cc"}
ARTICLE_PATH_RE = re.compile(r"^/bbs/(?P<board>[^/]+)/(?P<aid>M\.[^/]+?)(?:\.html)?/?$")
DATE_TIME_RE = re.compile(r"(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})")
FLOOR_RE = re.compile(r"(?P<floor>\d+)\s*F")
COUNT_RE = re.compile(r"留言\s*(?P<count>\d+)\s*則")
THREAD_TITLE_RE = re.compile(r"Hololive\s+(?:本日|日間|晚間)直播單")


@dataclass(frozen=True)
class WebPush:
    floor: int
    kind: str
    author: str
    content: str
    ptt_date: str
    ptt_time: str


@dataclass(frozen=True)
class WebArticle:
    board: str
    aid: str
    title: str
    source_url: str
    declared_push_count: int
    pushes: tuple[WebPush, ...]
    body_text: str | None = None


@dataclass(frozen=True)
class WebArticleCandidate:
    title: str
    source_url: str


def parse_article_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in PTTWEB_HOSTS:
        raise ValueError("目前只接受 https://www.pttweb.cc 的文章網址")
    match = ARTICLE_PATH_RE.match(parsed.path)
    if match is None:
        raise ValueError("網址不是可辨識的 PTT Web 文章網址")
    return match.group("board"), match.group("aid")


def normalize_dom_push(row: dict[str, object]) -> WebPush:
    datetime_match = DATE_TIME_RE.search(str(row.get("datetime", "")))
    floor_match = FLOOR_RE.search(str(row.get("floor", "")))
    if datetime_match is None or floor_match is None:
        raise ValueError(f"推文缺少樓層或時間：{row!r}")
    kind = str(row.get("kind", "")).strip()
    author = str(row.get("author", "")).strip()
    if kind not in {"推", "噓", "→"} or not author:
        raise ValueError(f"推文格式不完整：{row!r}")
    return WebPush(
        floor=int(floor_match.group("floor")),
        kind=kind,
        author=author,
        content=str(row.get("content", "")).strip(),
        ptt_date=datetime_match.group("date"),
        ptt_time=datetime_match.group("time"),
    )


def validate_pushes(pushes: Sequence[WebPush], declared_count: int) -> None:
    if declared_count <= 0:
        raise ValueError("網頁沒有提供有效的推文總數")
    if len(pushes) != declared_count:
        raise ValueError(
            f"推文數不完整：網頁宣告 {declared_count} 則，實際解析 {len(pushes)} 則"
        )
    floors = [push.floor for push in pushes]
    expected = list(range(1, declared_count + 1))
    if floors != expected:
        missing = sorted(set(expected) - set(floors))[:10]
        duplicated = sorted({value for value in floors if floors.count(value) > 1})[:10]
        raise ValueError(f"樓層不連續；缺少={missing}，重複={duplicated}")


def parse_dom_pushes(rows: Sequence[dict[str, object]], declared_count: int) -> tuple[WebPush, ...]:
    """Ignore floorless quoted content before 1F, but validate every real floor."""
    pushes: list[WebPush] = []
    for row in rows:
        if FLOOR_RE.search(str(row.get("floor", ""))):
            pushes.append(normalize_dom_push(row))
        elif pushes:
            raise ValueError(f"推文區出現無樓層元素：{row!r}")
    validate_pushes(pushes, declared_count)
    return tuple(pushes)


def parse_body_parts(parts: Sequence[dict[str, str]]) -> str:
    """Keep article text and full anchor targets, without media widgets or comments."""
    if not parts:
        raise ValueError("網頁中找不到文章本文")
    chunks: list[str] = []
    for part in parts:
        value = part.get("text", "")
        url = part.get("url", "")
        if url:
            if not urlparse(url).scheme in {"http", "https"}:
                raise ValueError("文章連結格式不完整")
            label = value.strip()
            value = url if not label or label == url else f"{label} ({url})"
        chunks.append(value)
    body = re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip()
    if not body:
        raise ValueError("文章本文為空")
    return body


def roc_date_marker(value: date) -> str:
    return f"{value.year - 1911:03d}{value.month:02d}{value.day:02d}"


def filter_candidates(
    rows: Sequence[dict[str, str]], marker: str
) -> tuple[WebArticleCandidate, ...]:
    expected_suffix = f"({marker})"
    found: dict[str, WebArticleCandidate] = {}
    for row in rows:
        title = row.get("title", "").strip()
        url = row.get("url", "").strip()
        if not THREAD_TITLE_RE.search(title) or expected_suffix not in title:
            continue
        try:
            parse_article_url(url)
        except ValueError:
            continue
        found[url] = WebArticleCandidate(title, url)
    return tuple(found[url] for url in sorted(found))


class PttWebClient:
    """Reuse one local Chrome process for discovery and article imports."""

    def __init__(self, *, timeout_seconds: int = 45) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - optional package
            raise RuntimeError(
                "缺少 Web 匯入套件；請先安裝 requirements-web.txt"
            ) from exc
        self.timeout_ms = timeout_seconds * 1000
        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        try:
            self._browser = self._playwright.chromium.launch(
                channel="chrome", headless=True
            )
        except Exception as exc:
            self._playwright.stop()
            raise RuntimeError("無法啟動本機 Google Chrome") from exc
        self._page = self._browser.new_page(locale="zh-TW")

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> "PttWebClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def discover_date(self, value: datetime.date) -> tuple[WebArticleCandidate, ...]:
        marker = roc_date_marker(value)
        query = quote(f"Hololive {marker}")
        search_url = f"https://www.pttweb.cc/bbs/C_Chat/search/t/{query}"
        response = self._page.goto(
            search_url, wait_until="domcontentloaded", timeout=self.timeout_ms
        )
        if response is None or response.status in {403, 429, 503}:
            raise RuntimeError("搜尋頁被拒絕或服務暫時不可用；停止回填")
        self._page.locator("main").wait_for(timeout=self.timeout_ms)
        rows = self._page.locator('a[href^="/bbs/C_Chat/M."]').evaluate_all(
            """links => links.map(link => ({
                title: (link.textContent || '').trim(),
                url: new URL(link.getAttribute('href'), location.origin).href
            }))"""
        )
        return filter_candidates(rows, marker)

    def fetch(self, url: str) -> WebArticle:
        board, aid = parse_article_url(url)
        page = self._page
        response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        if response is None or response.status in {403, 429, 503}:
            raise RuntimeError("文章頁被拒絕或服務暫時不可用；停止回填")
        page.locator('[itemprop="headline"]').wait_for(timeout=self.timeout_ms)
        body = self._read_body(page)

        body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
        count_match = COUNT_RE.search(body_text)
        if count_match is None:
            raise RuntimeError("網頁中找不到推文總數")
        declared_count = int(count_match.group("count"))

        load_all = page.get_by_text("載入全部", exact=True)
        if load_all.count():
            load_all.click(timeout=self.timeout_ms)
        self._wait_for_all_comments(page, declared_count, load_all)

        title = page.locator('[itemprop="headline"]').first.inner_text().strip()
        rows = page.locator('[itemprop="comment"]').evaluate_all(
            """nodes => nodes.map(node => ({
                kind: node.querySelector('.e7-left')?.textContent || '',
                author: node.querySelector('[itemprop=name]')?.textContent || '',
                content: node.querySelector('[itemprop=text]')?.textContent || '',
                datetime: node.querySelector('.e7-ipdatetime1')?.textContent || '',
                floor: node.querySelector('.e7-floor')?.textContent || ''
            }))"""
        )
        pushes = parse_dom_pushes(rows, declared_count)
        return WebArticle(board, aid, title, url, declared_count, pushes, body)

    def fetch_body(self, url: str) -> str:
        """Read only the article body; do not expand or refresh its comments."""
        parse_article_url(url)
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        if response is None or response.status in {403, 429, 503}:
            raise RuntimeError("文章頁被拒絕或服務暫時不可用；停止回填")
        self._page.locator('[itemprop="headline"]').wait_for(timeout=self.timeout_ms)
        return self._read_body(self._page)

    def _read_body(self, page) -> str:
        page.locator('[itemprop="articleBody"].e7-main-content').first.wait_for(
            timeout=self.timeout_ms
        )
        parts = page.locator('[itemprop="articleBody"].e7-main-content').evaluate_all(
            """nodes => nodes.flatMap(node => {
                const walk = item => {
                    if (item.nodeType === Node.TEXT_NODE) return [{text: item.textContent || ''}];
                    if (item.nodeType !== Node.ELEMENT_NODE) return [];
                    if (item.matches('[itemprop="comment"], .e7-richcontent, '
                        + '.e7-youtube-resize-container, script, style, button, iframe, img, video')) return [];
                    if (item.tagName === 'BR') return [{text: '\\n'}];
                    if (item.tagName === 'A') return [{
                        text: item.textContent || '', url: item.href || ''
                    }];
                    const children = Array.from(item.childNodes).flatMap(walk);
                    return ['DIV', 'P', 'LI'].includes(item.tagName)
                        ? [{text: '\\n'}, ...children, {text: '\\n'}] : children;
                };
                return [...Array.from(node.childNodes).flatMap(walk), {text: '\\n'}];
            })"""
        )
        return parse_body_parts(parts)

    def _wait_for_all_comments(self, page, declared_count: int, load_all) -> None:
        """Wait with progress, retrying the site's occasionally missed click once."""
        started = time.monotonic()
        deadline = started + self.timeout_ms / 1000
        last_count = -1
        last_report = 0.0
        forced_click = False
        while True:
            current = page.locator('[itemprop="comment"]').evaluate_all(
                r"""nodes => nodes.filter(node => /\d+\s*F/.test(
                    node.querySelector('.e7-floor')?.textContent || ''
                )).length"""
            )
            now = time.monotonic()
            if current != last_count or now - last_report >= 15:
                print(
                    f"        網頁已展開 {current}/{declared_count} 則…",
                    flush=True,
                )
                last_count = current
                last_report = now
            if current == declared_count:
                return
            if current > declared_count:
                raise RuntimeError(
                    f"網頁實際出現 {current} 則，超過宣告的 {declared_count} 則"
                )
            # Some local Chrome builds acknowledge Playwright's click but Vue
            # does not receive it.  A native DOM click is a safe one-time retry.
            if not forced_click and now - started >= 5 and load_all.count():
                load_all.evaluate("element => element.click()")
                forced_click = True
                print("        展開按鈕未生效，已自動重試一次。", flush=True)
            if now >= deadline:
                button_left = bool(load_all.count())
                raise RuntimeError(
                    "完整推文展開逾時："
                    f"目前 {current}/{declared_count} 則；"
                    f"載入全部按鈕={'仍存在' if button_left else '已消失'}"
                )
            page.wait_for_timeout(1000)


def fetch_with_chrome(url: str, *, timeout_seconds: int = 45) -> WebArticle:
    """Compatibility wrapper for importing one article."""
    parse_article_url(url)
    with PttWebClient(timeout_seconds=timeout_seconds) as client:
        return client.fetch(url)


class WebBackfillDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 15000")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS web_articles (
                id INTEGER PRIMARY KEY,
                board TEXT NOT NULL,
                aid TEXT NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                declared_push_count INTEGER NOT NULL,
                parsed_push_count INTEGER NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(board, aid)
            );
            CREATE TABLE IF NOT EXISTS web_pushes (
                id INTEGER PRIMARY KEY,
                web_article_id INTEGER NOT NULL REFERENCES web_articles(id),
                floor INTEGER NOT NULL,
                kind TEXT NOT NULL,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                ptt_date TEXT NOT NULL,
                ptt_time TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(web_article_id, floor)
            );
            CREATE INDEX IF NOT EXISTS web_pushes_article_floor
                ON web_pushes(web_article_id, floor);
            CREATE TABLE IF NOT EXISTS web_article_bodies (
                web_article_id INTEGER PRIMARY KEY REFERENCES web_articles(id),
                body_text TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def store(self, article: WebArticle) -> tuple[int, int]:
        validate_pushes(article.pushes, article.declared_push_count)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO web_articles (
                    board, aid, title, source_url, declared_push_count,
                    parsed_push_count, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(board, aid) DO UPDATE SET
                    title=excluded.title,
                    source_url=excluded.source_url,
                    declared_push_count=excluded.declared_push_count,
                    parsed_push_count=excluded.parsed_push_count,
                    fetched_at=excluded.fetched_at
                """,
                (article.board, article.aid, article.title, article.source_url,
                 article.declared_push_count, len(article.pushes), now),
            )
            row = self.connection.execute(
                "SELECT id FROM web_articles WHERE board=? AND aid=?",
                (article.board, article.aid),
            ).fetchone()
            assert row is not None
            article_id = int(row["id"])
            if article.body_text is not None:
                self._store_body(article_id, article.body_text, now)
            for push in article.pushes:
                self.connection.execute(
                    """
                    INSERT INTO web_pushes (
                        web_article_id, floor, kind, author, content,
                        ptt_date, ptt_time, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(web_article_id, floor) DO UPDATE SET
                        kind=excluded.kind, author=excluded.author,
                        content=excluded.content, ptt_date=excluded.ptt_date,
                        ptt_time=excluded.ptt_time, fetched_at=excluded.fetched_at
                    """,
                    (article_id, push.floor, push.kind, push.author, push.content,
                     push.ptt_date, push.ptt_time, now),
                )
        total = int(self.connection.execute(
            "SELECT COUNT(*) FROM web_pushes WHERE web_article_id=?", (article_id,)
        ).fetchone()[0])
        return article_id, total

    def _store_body(self, article_id: int, body: str, now: str) -> None:
        if not body.strip():
            raise ValueError("文章本文為空")
        self.connection.execute(
            "INSERT INTO web_article_bodies (web_article_id, body_text, fetched_at) "
            "VALUES (?, ?, ?) ON CONFLICT(web_article_id) DO UPDATE SET "
            "body_text=excluded.body_text, fetched_at=excluded.fetched_at",
            (article_id, body, now),
        )

    def missing_bodies(self, limit: int) -> list[tuple[int, str]]:
        return [(row[0], row[1]) for row in self.connection.execute(
            "SELECT a.id, a.source_url FROM web_articles a "
            "LEFT JOIN web_article_bodies b ON b.web_article_id=a.id "
            "WHERE b.web_article_id IS NULL ORDER BY a.id DESC LIMIT ?", (limit,)
        )]

    def store_existing_body(self, article_id: int, body: str) -> None:
        with self.connection:
            self._store_body(article_id, body, datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def has_complete_article(self, url: str) -> bool:
        """Skip only articles whose saved floors still pass the original checks."""
        board, aid = parse_article_url(url)
        row = self.connection.execute(
            "SELECT id, declared_push_count, parsed_push_count FROM web_articles "
            "WHERE board=? AND aid=?", (board, aid),
        ).fetchone()
        if row is None:
            return False
        floors = [item[0] for item in self.connection.execute(
            "SELECT floor FROM web_pushes WHERE web_article_id=? ORDER BY floor",
            (row["id"],),
        )]
        count = row["declared_push_count"]
        return (count > 0 and row["parsed_push_count"] == count
                and floors == list(range(1, count + 1)))

    def close(self) -> None:
        self.connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="從 PTT Web 鏡像匯入單篇完整推文")
    parser.add_argument("url", help="https://www.pttweb.cc/bbs/... 的文章網址")
    parser.add_argument(
        "--database", default="web_backfill_test.sqlite3",
        help="測試資料庫路徑（預設不碰正式資料庫）",
    )
    parser.add_argument("--timeout", type=int, default=45, help="網頁等待秒數")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("正在以 Web 模式讀取文章；不會登入 PTT BBS…")
    article = fetch_with_chrome(args.url, timeout_seconds=args.timeout)
    database = WebBackfillDatabase(args.database)
    try:
        _article_id, total = database.store(article)
    finally:
        database.close()
    print(f"標題：{article.title}")
    print(f"文章：{article.board} {article.aid}")
    print(f"推文：{total}/{article.declared_push_count} 則，樓層 1～{total}")
    print(f"資料庫：{Path(args.database).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
