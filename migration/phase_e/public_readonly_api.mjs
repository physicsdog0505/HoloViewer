/* 8788 Phase E — isolated, read-only Cloudflare API boundary.
 * This module is not deployed or wired into Public main.
 * All data is obtained from the externally owned Public API; never from
 * local 4174 Python, SQLite or browser-held credentials.
 */
const ROUTES = Object.freeze({
  today: "/v1/catalog/today",
  history: "/v1/history",
  ptt: "/v1/ptt",
});
const VIDEO_RE = /^[A-Za-z0-9_-]{11}$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const AID_RE = /^[A-Za-z0-9._-]{1,32}$/;

export function endpointFor(kind, input = {}) {
  if (!Object.hasOwn(ROUTES, kind)) throw new TypeError("unsupported endpoint");
  const query = new URLSearchParams();
  if (kind === "history") {
    if (!DAY_RE.test(input.day ?? "")) throw new TypeError("history day required");
    const limit = input.limit ?? 50;
    const offset = input.offset ?? 0;
    if (!Number.isInteger(limit) || limit < 1 || limit > 100 ||
        !Number.isInteger(offset) || offset < 0) throw new TypeError("invalid history page");
    query.set("day", input.day);
    query.set("limit", String(limit));
    query.set("offset", String(offset));
  }
  if (kind === "ptt") {
    if (!AID_RE.test(input.aid ?? "")) throw new TypeError("verified PTT AID required");
    query.set("aid", input.aid);
    if (input.cursor != null) {
      if (typeof input.cursor !== "string" || input.cursor.length > 512)
        throw new TypeError("invalid cursor");
      query.set("cursor", input.cursor);
    }
  }
  return ROUTES[kind] + (query.size ? "?" + query : "");
}

export function videoEndpoint(videoId) {
  if (!VIDEO_RE.test(videoId ?? "")) throw new TypeError("invalid video id");
  return "/v1/catalog/videos/" + encodeURIComponent(videoId);
}

export async function readPublicApi(apiBase, endpoint, { fetchImpl = fetch, signal } = {}) {
  const base = new URL(apiBase);
  if (base.protocol !== "https:" || base.username || base.password ||
      base.search || base.hash) throw new TypeError("HTTPS API origin required");
  if (!endpoint.startsWith("/v1/") || endpoint.startsWith("//"))
    throw new TypeError("endpoint outside Public read-only API");
  const url = new URL(endpoint, base.origin);
  if (url.origin !== base.origin) throw new TypeError("cross-origin endpoint rejected");
  const response = await fetchImpl(url.toString(), {
    method: "GET",
    mode: "cors",
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new Error("Public API unavailable: HTTP " + response.status);
  const body = await response.json();
  if (!body || typeof body !== "object" || Array.isArray(body))
    throw new TypeError("invalid Public API response");
  return body;
}
