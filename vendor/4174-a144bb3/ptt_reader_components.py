"""Shared 8501 PTT replay and typography component for HTML player surfaces."""
from __future__ import annotations



def replay_timeline_messages(messages):
    """Assign simulated arrivals per original PTT minute, preserving real start offsets."""
    result = []
    position = 0
    while position < len(messages):
        first = messages[position]
        base = float(first["offset"])
        clock = first.get("clock")
        end = position + 1
        while (end < len(messages)
               and messages[end].get("clock") == clock
               and float(messages[end]["offset"]) - base < 60):
            end += 1
        count = end - position
        # The next minute may start in under three seconds: never let replay
        # arrivals cross its first row (binary search requires sorted offsets).
        gap = (float(messages[end]["offset"]) - base) if end < len(messages) else 60.0
        spacing = min(3.0, max(0.0, gap) / count)
        for index, item in enumerate(messages[position:end]):
            row = dict(item)
            row["watchalong_replay_offset"] = round(base + index * spacing, 3)
            result.append(row)
        position = end
    return tuple(result)


REPLAY_JS = r"""
function pttReplayUpperBound(messages, seconds) {
  let low = 0, high = messages.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (Number(messages[mid].watchalong_replay_offset ?? messages[mid].offset ?? 0) <= seconds)
      low = mid + 1;
    else high = mid;
  }
  return low;
}
function pttReaderAttach(feedId, fontDefault) {
  const feed = document.getElementById(feedId);
  const slider = document.getElementById(feedId + '-font');
  const label = document.getElementById(feedId + '-font-label');
  const latest = document.getElementById(feedId + '-latest');
  const follow = document.getElementById(feedId === 'ptt-feed' ? 'ptt-follow' : 'follow');
  if (!feed) return;
  function apply() {
    const px = slider ? Number(slider.value) : fontDefault;
    if (feed.style && typeof feed.style.setProperty === 'function') {
      feed.style.setProperty('--ptt-reader-font', px + 'px');
    }
    if (label) label.textContent = px + 'px';
  }
  if (slider && typeof slider.addEventListener === 'function') slider.addEventListener('input', apply);
  apply();
  if (latest && typeof latest.addEventListener === 'function') latest.addEventListener('click', () => {
    if (follow) follow.checked = true;
    feed.scrollTop = feed.scrollHeight;
  });
}
"""


def decorate_ptt_reader_html(html: str, *, feed_id: str = 'chat', default_font: int = 14) -> str:
    """Add the same user-owned font controls and latest action to each reader."""
    default_font = max(12, min(26, int(default_font)))
    header_id = 'ptt-head' if feed_id == 'ptt-feed' else 'chat-head'
    header_start = f'<div id="{header_id}">'
    if header_start not in html:
        raise ValueError(f'missing PTT reader header: {header_id}')
    font_html = (
        f'<label class="ptt-reader-font-control">字體 '
        f'<input id="{feed_id}-font" type="range" min="12" max="26" step="2" '
        f'value="{default_font}" aria-label="PTT 推文字體大小">'
        f'<span id="{feed_id}-font-label">{default_font}px</span></label>'
    )
    latest_html = f'<button id="{feed_id}-latest" type="button">最新</button>'
    # Do not duplicate a legacy control when upgrading the watchalong reader.
    if feed_id == 'ptt-feed':
        html = html.replace('<button type="button" id="ptt-latest">最新</button>', '', 1)
    if feed_id == 'chat':
        # Remove the one-off 3/4-stream font slider; all three readers use this component.
        old = ('<label class="chat-font-control" for="chat-font-size">字體 '
               '<input id="chat-font-size" type="range" min="12" max="26" step="2" '
               'value="14" aria-label="PTT 推文字體大小">'
               '<span id="chat-font-label">14px</span></label>')
        html = html.replace(old, '', 1)
    html = html.replace(header_start, header_start + latest_html + font_html, 1)
    css = (
        f'#{feed_id} {{ --ptt-reader-font:{default_font}px; display:flex; flex-direction:column; }}\n'
        f'#{feed_id} > .row:nth-child(2), #{feed_id} > .ptt-row:first-child {{ margin-top:auto; }}\n'
        f'#{feed_id} .row, #{feed_id} .ptt-row {{ font-size:var(--ptt-reader-font,{default_font}px); }}\n'
        '.ptt-reader-font-control { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }\n'
        '.ptt-reader-font-control input { width:92px; accent-color:#7db2ff; }\n'
        f'#{header_id} {{ flex-wrap:wrap; align-items:center; gap:7px; }}\n'
    )
    html = html.replace('</style>', css + '</style>', 1)
    # Always inject a standalone executable script rather than assuming the
    # preceding script is immediately adjacent to </body>. Whitespace, layout,
    # or a different player template must not silently omit replay helpers.
    closing = '</body></html>'
    if closing not in html:
        raise ValueError('missing closing HTML body for PTT reader')
    # The watchalong extras script performs an immediate updatePtt(0), so the
    # replay lookup MUST be declared before that script executes.
    watchalong_anchor = '<script>\nconst watchalongPttSeed='
    if feed_id == 'ptt-feed' and watchalong_anchor in html:
        html = html.replace(watchalong_anchor,
                            '<script>\n' + REPLAY_JS + '\n</script>' + watchalong_anchor, 1)
        reader_script = f"<script>pttReaderAttach('{feed_id}', {default_font});</script>"
    else:
        # Preserve the single-script contract used by sync/multistream players.
        # Their existing browser and Node VM test harnesses extract one script.
        return html.replace("</script></body></html>",
            REPLAY_JS + f"\npttReaderAttach('{feed_id}', {default_font});\n" + "</script></body></html>", 1)
    html = html.replace(closing, reader_script + closing, 1)
    return html
