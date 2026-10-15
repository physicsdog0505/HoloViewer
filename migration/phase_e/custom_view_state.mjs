/* Accepted 4174 custom-view behavior, portable to a persistent static shell.
 * Pure state; DOM and YouTube iframe lifecycle are integration responsibilities.
 */
const VIDEO_RE = /^[A-Za-z0-9_-]{11}$/;
export function normalizeVideoId(value) {
  const input = String(value ?? "").trim();
  if (VIDEO_RE.test(input)) return input;
  let u;
  try { u = new URL(input); } catch { return null; }
  if (!["youtube.com","www.youtube.com","m.youtube.com","youtu.be","www.youtu.be"].includes(u.hostname)) return null;
  let id = null;
  if (u.hostname.endsWith("youtu.be")) id = u.pathname.split("/")[1];
  else if (u.pathname === "/watch") id = u.searchParams.get("v");
  else if (["live","embed","shorts"].includes(u.pathname.split("/")[1])) id = u.pathname.split("/")[2];
  return VIDEO_RE.test(id || "") ? id : null;
}

export function createCustomViewState() {
  let videos = [];
  let primary = null;
  let audio = null;
  let layout = "auto";
  let ptt = "live";
  const selected = () => new Set(videos);
  function normalize() {
    if (!selected().has(primary)) primary = videos[0] ?? null;
    if (!selected().has(audio)) audio = videos[0] ?? null;
    if (videos.length < 2) layout = "auto";
  }
  return Object.freeze({
    snapshot() {
      return Object.freeze({ videos: [...videos], primary, audio, layout, ptt });
    },
    add(input) {
      const id = normalizeVideoId(input);
      if (!id || videos.includes(id)) return false;
      videos.push(id); normalize(); return true;
    },
    remove(input) {
      const id = normalizeVideoId(input);
      if (!videos.includes(id)) return false;
      videos = videos.filter(v => v !== id); normalize(); return true;
    },
    move(from, to) {
      if (![from,to].every(Number.isInteger) || from < 0 || to < 0 ||
          from >= videos.length || to >= videos.length || from === to) return false;
      const [item] = videos.splice(from, 1);
      videos.splice(to, 0, item);
      normalize(); return true;
    },
    setPrimary(id) {
      if (!videos.includes(id)) return false;
      primary = id; return true;
    },
    setAudio(id) {
      if (!videos.includes(id)) return false;
      audio = id; return true;
    },
    setLayout(value) {
      if (!["auto","grid","focus"].includes(value)) return false;
      layout = videos.length > 1 ? value : "auto"; return true;
    },
    setPtt(value) {
      if (!["live","video"].includes(value)) return false;
      ptt = value; return true;
    },
    sessionQuery() {
      if (videos.length === 0) throw new Error("no selected videos");
      const q = new URLSearchParams();
      for (const id of videos) q.append("stream",id);
      q.set("layout",videos.length === 1 ? "auto" : layout);
      q.set("ptt",ptt);
      q.set("primary",String(videos.indexOf(primary)));
      q.set("audio",String(videos.indexOf(audio)));
      return q.toString();
    }
  });
}
