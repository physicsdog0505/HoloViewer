"""Safe HTML renderer for the compact, auto-following push stream."""

from __future__ import annotations

import json


def _message(push) -> dict[str, str | int]:
    floor_val = getattr(push, "floor", None)
    return {
        "key": f"{push.article_id}:{push.source_line}",
        "kind": push.kind,
        "author": push.author,
        "content": push.content,
        "time": push.occurred_at.strftime("%H:%M"),
        "date": push.occurred_at.strftime("%m/%d"),
        "url": push.article_url,
        "floor": floor_val if floor_val is not None else "",
    }



def build_chat_html(
    pushes,
    *,
    font_size: int = 16,
    auto_follow: bool = True,
    animate_new: bool = True,
    message_delay_ms: int = 3000,
    theme: str = "modern",
    storage_key: str = "hololive-ptt-live",
    search_query: str = "",
    search_mode: str = "filter",
) -> str:
    """Build a self-contained chat panel.

    Text is passed through JSON and inserted with DOM ``textContent`` rather
    than HTML, so PTT content cannot inject markup or script into the reader.
    """
    payload = json.dumps([_message(push) for push in pushes], ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    storage = json.dumps(storage_key)
    follow = "true" if auto_follow else "false"
    animate = "true" if animate_new else "false"
    delay = max(100, min(int(message_delay_ms), 10000))
    search_query_json = json.dumps(search_query, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    search_mode_json = json.dumps(search_mode, ensure_ascii=False)
    if theme == "ptt":
        font_family = 'Menlo, Monaco, "Noto Sans Mono CJK TC", monospace'
        push_color = "#f4f4f4"
        arrow_color = "#ff3030"
        author_color = "#ffff00"
        content_color = "#a9a900"
        time_color = "#dedede"
    else:
        font_family = '-apple-system, BlinkMacSystemFont, "Noto Sans TC", sans-serif'
        push_color = "#ffd54a"
        arrow_color = "#c8c8c8"
        author_color = "#58d7ff"
        content_color = "#f1f1f1"
        time_color = "#777"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; background: #080808; color: #f2f2f2;
  font-family: {font_family}; }}
#chat {{ height: 100vh; overflow-y: auto; overscroll-behavior: contain;
  scrollbar-color: #555 #111; padding: 6px 8px 12px; }}
.row {{ display: grid; grid-template-columns: 1.3em minmax(92px, auto) 1fr;
  column-gap: 6px; align-items: start; padding: 4px 2px;
  border-bottom: 1px solid #191919; font-size: {int(font_size)}px; line-height: 1.45; }}
.row.highlighted {{ background: rgba(255, 213, 74, 0.14) !important; border-left: 3px solid #ffd54a; padding-left: 3px; }}
mark.kw-highlight {{ background: #ffd54a; color: #111; border-radius: 2px; padding: 0 2px; font-weight: 700; }}
.kind {{ font-weight: 800; text-align: center; }}
.kind-push {{ color: {push_color}; }} .kind-boo {{ color: #ff4b4b; }}
.kind-arrow {{ color: {arrow_color}; }}
.body {{ min-width: 0; overflow-wrap: anywhere; }}
.author {{ color: {author_color}; font-weight: 650; margin-right: .45em; }}
.content {{ color: {content_color}; white-space: pre-wrap; }}
.meta {{ color: {time_color}; font-size: .72em; white-space: nowrap; padding-top: .25em; }}
.floor {{ color: #777; font-size: .88em; margin-left: 2px; font-weight: normal; opacity: .8; }}
.new {{ visibility: hidden; }}
#newest {{ position: fixed; right: 16px; bottom: 14px; z-index: 5;
  border: 1px solid #777; border-radius: 999px; padding: 7px 12px;
  color: #fff; background: rgba(35,35,35,.92); cursor: pointer; display: none; }}
#empty {{ color: #aaa; padding: 18px 10px; text-align: center; }}
@media (max-width: 430px) {{
  #chat {{ padding-left: 5px; padding-right: 5px; }}
  .row {{ grid-template-columns: 1.2em minmax(84px, auto) 1fr; column-gap: 4px; }}
  .author {{ display: inline; }}
}}
</style></head><body><div id="chat"></div><button id="newest">最新</button><script>
const messages = {payload};
const storageKey = {storage};
const autoFollow = {follow};
const animateNew = {animate};
const searchQuery = ({search_query_json}).trim();
const searchMode = {search_mode_json};
const chat = document.getElementById('chat');
const newest = document.getElementById('newest');
let previous = null;
try {{ previous = sessionStorage.getItem(storageKey); }} catch (_) {{}}
let previousIndex = previous ? messages.findIndex(m => m.key === previous) : -1;
let firstVisit = !previous;
let unseenStart = previousIndex >= 0 ? previousIndex + 1 : messages.length;

function appendHighlightedText(container, text, query) {{
  if (!query) {{
    container.textContent = text;
    return;
  }}
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  let pos = 0;
  while (pos < text.length) {{
    const matchIdx = lowerText.indexOf(lowerQuery, pos);
    if (matchIdx === -1) {{
      container.appendChild(document.createTextNode(text.slice(pos)));
      break;
    }}
    if (matchIdx > pos) {{
      container.appendChild(document.createTextNode(text.slice(pos, matchIdx)));
    }}
    const mark = document.createElement('mark');
    mark.className = 'kw-highlight';
    mark.textContent = text.slice(matchIdx, matchIdx + query.length);
    container.appendChild(mark);
    pos = matchIdx + query.length;
  }}
}}

function checkMatch(message, query) {{
  if (!query) return false;
  const q = query.toLowerCase();
  if (message.content && message.content.toLowerCase().includes(q)) return true;
  if (message.author && message.author.toLowerCase().includes(q)) return true;
  if (message.floor !== undefined && message.floor !== null && message.floor !== '') {{
    const fStr = String(message.floor);
    if (fStr.includes(q) || (fStr + '樓').toLowerCase().includes(q)) return true;
  }}
  return false;
}}

function makeRow(message, hidden) {{
  const row = document.createElement('div');
  const isMatch = checkMatch(message, searchQuery);
  row.className = 'row' + (hidden ? ' new' : '') + (isMatch ? ' highlighted' : '');
  const kind = document.createElement('div');
  kind.className = 'kind ' + (message.kind === '推' ? 'kind-push' : message.kind === '噓' ? 'kind-boo' : 'kind-arrow');
  kind.textContent = message.kind;
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = message.time;
  if (message.floor) {{
    const floorSpan = document.createElement('span');
    floorSpan.className = 'floor';
    appendHighlightedText(floorSpan, message.floor + '樓', searchQuery);
    meta.append(' ', floorSpan);
  }}
  const body = document.createElement('div');
  body.className = 'body';
  const author = document.createElement('span');
  author.className = 'author';
  appendHighlightedText(author, message.author + ':', searchQuery);
  const content = document.createElement('span');
  content.className = 'content';
  appendHighlightedText(content, message.content, searchQuery);
  body.append(author, content);
  row.append(kind, meta, body);
  const floorTag = message.floor ? (' · ' + message.floor + '樓') : '';
  row.title = message.date + floorTag + ' · 點兩下開啟 PTT 原文';
  row.ondblclick = () => window.open(message.url, '_blank', 'noopener');
  return row;
}}

if (!messages.length) {{
  const empty = document.createElement('div'); empty.id = 'empty';
  empty.textContent = '目前沒有符合條件的推文。'; chat.appendChild(empty);
}} else {{
  messages.forEach((message, index) =>
    chat.appendChild(makeRow(message, animateNew && !firstVisit && index >= unseenStart)));
}}
const freshRows = Array.from(chat.querySelectorAll('.new'));
const count = freshRows.length;
const delay = {delay};
let flushed = false;
let timer = null;
let ignoreScrollUntil = 0;

function moveTo(row) {{
  if (!autoFollow || !row) return;
  ignoreScrollUntil = performance.now() + 250;
  chat.scrollTop = Math.max(0, row.offsetTop + row.offsetHeight - chat.clientHeight + 8);
}}

function save(message) {{
  try {{ sessionStorage.setItem(storageKey, message.key); }} catch (_) {{}}
}}

function flushAll() {{
  if (!count || flushed) return;
  flushed = true;
  if (timer) clearTimeout(timer);
  freshRows.forEach(row => row.style.visibility = 'visible');
  save(messages[messages.length - 1]);
  newest.style.display = 'none';
  ignoreScrollUntil = performance.now() + 250;
  chat.scrollTop = chat.scrollHeight;
}}

newest.onclick = flushAll;
chat.addEventListener('scroll', () => {{
  if (!count || flushed || performance.now() < ignoreScrollUntil) return;
  if (chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 24) flushAll();
}});

if (count) {{
  newest.style.display = 'block';
  moveTo(freshRows[0].previousElementSibling || freshRows[0]);
}} else if (autoFollow) {{
  chat.scrollTop = chat.scrollHeight;
}}

function reveal(index) {{
  if (flushed || index >= count) {{
    newest.style.display = 'none';
    return;
  }}
  freshRows[index].style.visibility = 'visible';
  moveTo(freshRows[index]);
  save(messages[unseenStart + index]);
  timer = setTimeout(() => reveal(index + 1), delay);
}}
if (count) reveal(0);
else if (messages.length) save(messages[messages.length - 1]);
</script></body></html>"""
