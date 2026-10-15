/* Navigation bridge: routing is separate from player mounting.
 * A browser shell owns one persistent host for its entire lifetime.
 */
import { createCustomViewState } from "./custom_view_state.mjs";

const VIDEO_RE = /^[A-Za-z0-9_-]{11}$/;
const LAYOUTS = new Set(["auto", "compare", "focus", "equal", "primary"]);

export function parseAcceptedSession(search) {
  const q = new URLSearchParams(String(search || "").replace(/^\?/, ""));
  const ids = q.getAll("stream");
  if (!ids.length || ids.length > 16 || ids.some(id => !VIDEO_RE.test(id)) ||
      new Set(ids).size !== ids.length) throw new TypeError("invalid session video selection");
  const layout = q.get("layout") ?? "auto";
  const ptt = q.get("ptt") ?? "live";
  const primary = Number(q.get("primary") ?? "0");
  const audio = Number(q.get("audio") ?? "0");
  if (!LAYOUTS.has(layout) || !["live","video"].includes(ptt) ||
      !Number.isInteger(primary) || !Number.isInteger(audio) ||
      primary < 0 || audio < 0 || primary >= ids.length || audio >= ids.length)
    throw new TypeError("invalid viewing session parameters");
  return { ids, layout, ptt, primary, audio };
}

export function createViewingRouteController(playerHost) {
  if (!playerHost || typeof playerHost.sync !== "function" ||
      typeof playerHost.activate !== "function") throw new TypeError("player host required");
  const selection = createCustomViewState();
  let currentRoute = null;
  return Object.freeze({
    selection,
    openSession(search) {
      const parsed = parseAcceptedSession(search);
      const next = createCustomViewState();
      for (const id of parsed.ids) next.add(id);
      next.setPrimary(parsed.ids[parsed.primary]);
      next.setAudio(parsed.ids[parsed.audio]);
      next.setLayout(parsed.layout);
      next.setPtt(parsed.ptt);
      // Keep existing iframe objects for retained IDs; only removed selections unmount.
      playerHost.sync(parsed.ids);
      currentRoute = "custom-session";
      playerHost.activate(true);
      return { ...next.snapshot(), ids: parsed.ids };
    },
    navigate(route) {
      const visible = route === "custom-session";
      playerHost.activate(visible);
      currentRoute = route;
      return { route: currentRoute, playersMounted: playerHost.ids() };
    },
    currentRoute() { return currentRoute; }
  });
}
