"""Browser transport shared by the single and multi-stream chat renderers."""

FEED_POLLING_JS = r"""
function startLivePushPolling(feed, start, intervalMs, initial, install) {
  if (!feed) return;
  let signature = JSON.stringify(initial), stopped = false, timer, controller;
  async function pollLivePushes() {
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const url = feed+'/pushes?start='+encodeURIComponent(start)+'&_='+Date.now();
      const response = await fetch(url, {cache:'no-store', signal:controller.signal});
      if (!response.ok) throw new Error('HTTP '+response.status);
      const payload = await response.json();
      if (!Array.isArray(payload.messages)) throw new Error('Invalid messages');
      const next = [...new Map(payload.messages.map(m => [m.key, m])).values()]
        .sort((a, b) => a.offset - b.offset);
      const nextSignature = JSON.stringify(next);
      if (!stopped && nextSignature !== signature) {
        install(next);
        signature = nextSignature;
      }
    } catch (error) { console.warn('PTT live feed update failed', error); }
    finally {
      clearTimeout(timeout);
      if (!stopped) timer = setTimeout(pollLivePushes, intervalMs);
    }
  }
  window.addEventListener('pagehide', () => {
    stopped = true; clearTimeout(timer); controller?.abort();
  }, {once:true});
  pollLivePushes();
}
"""
