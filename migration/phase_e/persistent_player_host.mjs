/* Persistent YouTube iframe host for the 8788 Cloudflare static shell.
 * Mount ONCE in the application shell. Route changes must not recreate frames.
 * No invisible playback: pause before leaving the visible viewing route.
 * This adapter is not a cross-browser background-playback implementation.
 */
const ID_RE = /^[A-Za-z0-9_-]{11}$/;
const EMBED_ORIGIN = "https://www.youtube-nocookie.com";

export function createPersistentPlayerHost(container, { origin } = {}) {
  if (!container || typeof container.appendChild !== "function")
    throw new TypeError("persistent player container required");
  if (!origin || !/^https?:\/\//.test(origin))
    throw new TypeError("site origin required for YouTube iframe API");
  const frames = new Map();
  let active = false;

  function pause(frame) {
    if (!frame?.contentWindow) return;
    frame.contentWindow.postMessage(JSON.stringify({
      event: "command", func: "pauseVideo", args: []
    }), EMBED_ORIGIN);
  }
  function create(id) {
    const iframe = container.ownerDocument.createElement("iframe");
    const url = new URL(EMBED_ORIGIN + "/embed/" + encodeURIComponent(id));
    url.searchParams.set("enablejsapi", "1");
    url.searchParams.set("origin", origin);
    iframe.src = url.toString();
    iframe.title = "YouTube player " + id;
    iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.allowFullscreen = true;
    iframe.dataset.videoId = id;
    container.appendChild(iframe);
    return iframe;
  }
  return Object.freeze({
    sync(ids) {
      if (!Array.isArray(ids) || ids.some(id => !ID_RE.test(id)) ||
          new Set(ids).size !== ids.length || ids.length > 16)
        throw new TypeError("invalid player selection");
      const wanted = new Set(ids);
      for (const [id, frame] of frames) {
        if (!wanted.has(id)) {
          pause(frame);
          frame.remove();
          frames.delete(id);
        }
      }
      for (const id of ids) if (!frames.has(id)) frames.set(id, create(id));
      for (const [id, frame] of frames) {
        frame.hidden = !active || !wanted.has(id);
      }
      return ids.map(id => frames.get(id));
    },
    activate(value) {
      active = !!value;
      if (!active) for (const frame of frames.values()) pause(frame);
      container.hidden = !active;
      for (const frame of frames.values()) frame.hidden = !active;
    },
    frameFor(id) { return frames.get(id) ?? null; },
    ids() { return [...frames.keys()]; },
    destroy() {
      for (const frame of frames.values()) { pause(frame); frame.remove(); }
      frames.clear();
      container.hidden = true;
      active = false;
    }
  });
}
