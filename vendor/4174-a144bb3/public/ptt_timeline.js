/* HoloViewer portable PTT timeline core.
 * Plain browser JavaScript: no Python, Node, SQLite, local-only endpoints or credentials.
 * Import with <script src="..."> on GitHub Pages or any HTTPS host.
 */
(function (root) {
  'use strict';
  const MAX_MESSAGES = 20000;
  function timestamp(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value > 1e11 ? value : value * 1000;
    }
    if (typeof value !== 'string' || !/(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value)) return NaN;
    return Date.parse(value);
  }
  function compare(a,b) {
    if(a.offset!==b.offset)return a.offset-b.offset;
    if(a.cursor!==null&&b.cursor!==null)return a.cursor-b.cursor;
    return a.source_order-b.source_order;
  }
  function normalize(payload, start) {
    const startMs = timestamp(start);
    if (!Number.isFinite(startMs)) throw new Error('Missing or invalid ISO livestream start');
    const rows = Array.isArray(payload) ? payload : payload && payload.messages;
    if (!Array.isArray(rows) || rows.length > MAX_MESSAGES) throw new Error('Invalid or oversized PTT feed');
    const seen = new Set();
    const normalized = [];
    rows.forEach(function (row, index) {
      if (!row || typeof row !== 'object') return;
      const key = String(row.key || row.push_id || '').trim();
      if (!key || seen.has(key)) return;
      const when = timestamp(row.timestamp || row.occurred_at);
      // An explicit offset is useful for vetted historical timelines.
      const offset = typeof row.offset === 'number' && Number.isFinite(row.offset)
        ? row.offset : (Number.isFinite(when) ? (when - startMs) / 1000 : NaN);
      if (!Number.isFinite(offset) || offset < 0) return;
      seen.add(key);
      normalized.push({
        key: key, offset: offset, kind: String(row.kind || ''),
        author: String(row.author || ''), content: String(row.content || ''),
        floor: row.floor == null ? null : String(row.floor),
        clock: String(row.clock || ''), article_url: typeof row.article_url === 'string' ? row.article_url : '',
        aid: typeof row.aid === 'string' ? row.aid : '',
        cursor: Number.isSafeInteger(row.cursor) && row.cursor >= 0 ? row.cursor : null,
        source_order: index
      });
    });
    normalized.sort(function (a, b) { return compare(a,b); });
    return normalized;
  }
  function visibleCount(messages, seconds) {
    if (!Number.isFinite(seconds)) return 0;
    let lo = 0, hi = messages.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (messages[mid].offset <= seconds) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function createTimeline(start, initial) {
    let messages = normalize(initial || [], start);
    return {
      snapshot: function () { return messages.slice(); },
      at: function (seconds) { return messages.slice(0, visibleCount(messages, seconds)); },
      count: function (seconds) { return visibleCount(messages, seconds); },
      update: function (incoming) {
        const previous = new Map(messages.map(function (m) { return [m.key, m]; }));
        normalize(incoming, start).forEach(function (m) { previous.set(m.key, m); });
        if (previous.size > MAX_MESSAGES) throw new Error('PTT feed too large');
        const next = Array.from(previous.values()).sort(compare);
        messages = next;
        return next.length;
      }
    };
  }
  // Host supplies a vetted HTTPS URL and an optional fetch implementation.
  // No hardcoded Worker routes, API secrets, or implicit local fallbacks.
  async function fetchFeed(url, fetcher) {
    const parsed = new URL(url, root.location ? root.location.href : 'https://example.invalid');
    if (parsed.protocol !== 'https:') throw new Error('PTT feed requires HTTPS');
    const response = await (fetcher || root.fetch)(parsed.href, {cache: 'no-store', credentials: 'omit'});
    if (!response.ok) throw new Error('PTT API HTTP ' + response.status);
    return response.json();
  }
  root.HoloViewerPttTimeline = Object.freeze({normalize: normalize, visibleCount: visibleCount, createTimeline: createTimeline, fetchFeed: fetchFeed});
})(typeof globalThis !== 'undefined' ? globalThis : this);
