(function () {
  "use strict";

  const MAX_JSON_BYTES = 2 * 1024 * 1024;
  const FETCH_TIMEOUT_MS = 8000;
  const RELAY_LIMIT = 200;
  const RELAY_POLL_MS = 5000;

  class PublicDataError extends Error {}

  function text(value) {
    return typeof value === "string" ? value : "";
  }

  function boundedString(value, field, max = 4096, required = false) {
    if (value == null && !required) return null;
    if (typeof value !== "string" || (required && !value) || value.length > max) {
      throw new PublicDataError(`${field} is invalid`);
    }
    return value;
  }

  function isoTime(value, field, required = true) {
    if (value == null && !required) return null;
    const raw = boundedString(value, field, 64, required);
    const date = new Date(raw);
    if (!raw || !raw.endsWith("Z") || Number.isNaN(date.getTime())) {
      throw new PublicDataError(`${field} must be a UTC-Z timestamp`);
    }
    return raw;
  }

  function safeSourceUrl(value, baseUrl) {
    if (value == null) return null;
    const raw = boundedString(value, "source URL", 2048, true);
    const url = new URL(raw, baseUrl);
    if (url.protocol !== "https:" && url.origin !== location.origin) {
      throw new PublicDataError("source URL must be same-origin or HTTPS");
    }
    if (url.username || url.password) {
      throw new PublicDataError("source URL must not contain credentials");
    }
    return url;
  }

  async function fetchJson(url, maxBytes = MAX_JSON_BYTES) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "omit",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new PublicDataError(`HTTP ${response.status}`);
      const announced = Number(response.headers.get("content-length") || 0);
      if (announced > maxBytes) throw new PublicDataError("artifact exceeds size limit");
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > maxBytes) throw new PublicDataError("artifact exceeds size limit");
      try {
        return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffer));
      } catch (error) {
        throw new PublicDataError(`artifact JSON is invalid (${error.name})`);
      }
    } catch (error) {
      if (error.name === "AbortError") throw new PublicDataError("artifact request timed out");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function status(target, state, message) {
    if (!target) return;
    target.dataset.state = state;
    target.textContent = message;
  }

  function clear(target) {
    while (target && target.firstChild) target.firstChild.remove();
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = String(content);
    return node;
  }

  function parseYouTubeId(value) {
    const raw = text(value).trim();
    if (/^[A-Za-z0-9_-]{11}$/.test(raw)) return raw;
    try {
      const url = new URL(raw);
      let id = url.searchParams.get("v");
      if (!id && url.hostname === "youtu.be") id = url.pathname.slice(1).split("/")[0];
      if (!id && url.pathname.startsWith("/live/")) id = url.pathname.split("/")[2];
      return /^[A-Za-z0-9_-]{11}$/.test(id || "") ? id : null;
    } catch (_) {
      return null;
    }
  }

  function embed(frame, videoId) {
    if (!frame) return;
    frame.replaceChildren();
    if (!videoId) return;
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?enablejsapi=1&playsinline=1`;
    iframe.title = "YouTube player";
    iframe.allow = "accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.allowFullscreen = true;
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    frame.append(iframe);
  }

  function validateConfig(value, configUrl) {
    if (!value || typeof value !== "object" || Array.isArray(value) || value.schema_version !== 1) {
      throw new PublicDataError("public config schema is incompatible");
    }
    const allowed = new Set(["schema_version", "environment", "generated_at", "sources", "watchalong_policy"]);
    for (const key of Object.keys(value)) if (!allowed.has(key)) throw new PublicDataError("public config contains unknown fields");
    isoTime(value.generated_at, "config.generated_at");
    const sources = value.sources;
    if (!sources || typeof sources !== "object" || Array.isArray(sources)) throw new PublicDataError("config.sources is invalid");
    return {
      environment: boundedString(value.environment, "config.environment", 64, true),
      generatedAt: value.generated_at,
      homepage: safeSourceUrl(sources.homepage, configUrl),
      ptt: safeSourceUrl(sources.ptt, configUrl),
      watchalong: safeSourceUrl(sources.watchalong, configUrl),
      transcripts: safeSourceUrl(sources.transcripts, configUrl),
      liveRelay: safeSourceUrl(sources.live_relay, configUrl),
      automaticFollowerPlayback: value.watchalong_policy?.automatic_follower_playback === true,
    };
  }

  async function loadConfig() {
    const script = document.currentScript || document.querySelector("script[data-public-config]");
    const raw = script?.dataset.publicConfig;
    if (!raw) throw new PublicDataError("public config path is missing");
    const configUrl = new URL(raw, document.baseURI);
    return validateConfig(await fetchJson(configUrl, 32 * 1024), configUrl);
  }

  function validatePush(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new PublicDataError("PTT push is invalid");
    const floor = raw.floor == null ? null : Number(raw.floor);
    const sourceLine = raw.source_line == null ? null : Number(raw.source_line);
    if (floor != null && (!Number.isSafeInteger(floor) || floor < 1)) throw new PublicDataError("PTT floor is invalid");
    if (sourceLine != null && (!Number.isSafeInteger(sourceLine) || sourceLine < 1)) throw new PublicDataError("PTT source_line is invalid");
    return {
      pushId: boundedString(raw.push_id, "push_id", 256, true),
      floor,
      sourceLine,
      kind: boundedString(raw.kind, "push.kind", 16, true),
      author: boundedString(raw.author, "push.author", 64, true),
      content: boundedString(raw.content, "push.content", 1000, true),
      occurredAt: isoTime(raw.occurred_at, "push.occurred_at", false),
      cursor: raw.cursor == null ? null : Number(raw.cursor),
    };
  }

  function pushOrder(a, b) {
    const af = a.floor ?? Number.MAX_SAFE_INTEGER;
    const bf = b.floor ?? Number.MAX_SAFE_INTEGER;
    if (af !== bf) return af - bf;
    const al = a.sourceLine ?? Number.MAX_SAFE_INTEGER;
    const bl = b.sourceLine ?? Number.MAX_SAFE_INTEGER;
    if (al !== bl) return al - bl;
    return text(a.occurredAt).localeCompare(text(b.occurredAt)) || a.pushId.localeCompare(b.pushId);
  }

  function renderPushes(target, pushes) {
    clear(target);
    for (const push of pushes.sort(pushOrder)) {
      const row = element("article", "ptt-push");
      const marker = push.floor == null ? "樓層未明" : `#${push.floor}`;
      row.append(element("span", "ptt-floor", marker));
      row.append(element("span", `ptt-kind kind-${push.kind}`, push.kind));
      row.append(element("strong", "ptt-author", push.author));
      row.append(element("span", "ptt-content", push.content));
      if (push.occurredAt) row.append(element("time", "ptt-time", new Date(push.occurredAt).toLocaleString("zh-TW")));
      target.append(row);
    }
  }

  async function loadPttArtifact(url) {
    if (!url) throw new PublicDataError("PTT public artifact is not configured");
    const value = await fetchJson(url);
    if (!value || value.schema_version !== 1 || !Array.isArray(value.articles)) throw new PublicDataError("PTT artifact schema is incompatible");
    isoTime(value.generated_at, "PTT generated_at");
    if (!["complete", "partial"].includes(value.completeness)) throw new PublicDataError("PTT completeness is invalid");
    return {
      snapshotId: boundedString(value.snapshot_id, "PTT snapshot_id", 256, true),
      generatedAt: value.generated_at,
      completeness: value.completeness,
      articles: value.articles.map((raw) => {
        if (!raw || typeof raw !== "object" || !Array.isArray(raw.pushes)) throw new PublicDataError("PTT article is invalid");
        return {
          articleId: boundedString(raw.article_id, "article_id", 256, true),
          board: boundedString(raw.board, "article.board", 64, true),
          aid: boundedString(raw.aid, "article.aid", 64, true),
          title: boundedString(raw.title, "article.title", 300, true),
          url: raw.url == null ? null : boundedString(raw.url, "article.url", 2048, true),
          completeness: ["complete", "partial", "unknown"].includes(raw.completeness) ? raw.completeness : "unknown",
          pushes: raw.pushes.map(validatePush),
        };
      }),
    };
  }

  function articleOption(article) {
    const option = document.createElement("option");
    option.value = article.articleId;
    option.textContent = article.title;
    return option;
  }

  function validateHome(value) {
    if (!value || value.schema_version !== 1 || !Array.isArray(value.streams)) throw new PublicDataError("homepage artifact schema is incompatible");
    isoTime(value.generated_at, "homepage generated_at");
    if (!["complete", "partial"].includes(value.completeness)) throw new PublicDataError("homepage completeness is invalid");
    return { completeness: value.completeness, streams: value.streams.map((raw) => ({
      streamId: boundedString(raw.stream_id, "stream_id", 256, true),
      videoId: parseYouTubeId(raw.video_id), title: boundedString(raw.title, "stream.title", 300, true),
      channelName: boundedString(raw.channel_name, "stream.channel_name", 128, true),
      group: boundedString(raw.group, "stream.group", 64, true),
      lifecycle: ["live", "upcoming", "ended", "missing", "unknown"].includes(raw.lifecycle) ? raw.lifecycle : "unknown",
    })) };
  }

  async function startHome(config) {
    const homeStatus = document.querySelector("[data-home-status]");
    if (!config.homepage) throw new PublicDataError("homepage public artifact is not configured");
    const artifact = validateHome(await fetchJson(config.homepage));
    status(homeStatus, artifact.completeness, artifact.completeness === "complete" ? `公開快照已載入（${artifact.streams.length} 筆）。` : `公開快照僅為部分資料（${artifact.streams.length} 筆）；缺席不代表沒有直播。`);
    const sections = new Map();
    const headings = { "現在直播中": "live", "即將開始": "upcoming", "狀態待更新": "unknown", "已結束": "ended" };
    document.querySelectorAll("#homeDynamic section.section").forEach((section) => {
      const target = section.querySelector(".client-grid");
      const key = headings[section.querySelector("h2")?.textContent?.trim()];
      if (target && key) { clear(target); sections.set(key, { section, target }); }
    });
    const rail = document.querySelector(".live-channel-rail");
    clear(rail);
    if (rail) rail.append(element("span", "live-channel-label", "直播頻道"));
    for (const stream of artifact.streams) {
      const bucket = sections.get(stream.lifecycle) || sections.get("unknown");
      if (!bucket) continue;
      const card = element("a", "client-card stream-card");
      card.href = stream.videoId ? `custom-view/session/?stream=${encodeURIComponent(stream.videoId)}` : "#";
      card.dataset.group = stream.group.toLowerCase();
      const thumb = element("div", "card-thumb");
      const overlay = element("div", "thumb-overlay");
      overlay.append(element("span", `thumb-badge ${stream.lifecycle}`, stream.lifecycle));
      thumb.append(overlay);
      const meta = element("div", "yt-meta");
      const avatar = element("span", "channel-avatar-ring");
      avatar.append(element("span", "channel-avatar-fallback", stream.channelName.slice(0, 1)));
      const copy = element("div", "yt-copy");
      copy.append(element("h3", "stream-title", stream.title));
      copy.append(element("div", "channel-name", `${stream.channelName} · ${stream.group}`));
      meta.append(avatar, copy); card.append(thumb, meta); bucket.target.append(card);
      if (stream.lifecycle === "live" && rail) {
        const item = element("a", "live-channel-rail-item"); item.href = card.href;
        item.dataset.group = stream.group.toLowerCase();
        item.append(element("span", "live-channel-avatar", stream.channelName.slice(0, 1)), element("strong", "", stream.channelName));
        rail.append(item);
      }
    }
    for (const { section, target } of sections.values()) section.hidden = !target.children.length;
    if (rail) rail.hidden = rail.querySelectorAll("a").length === 0;
    document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
      const filter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll(".stream-card[data-group],.live-channel-rail-item[data-group]").forEach((item) => {
        item.hidden = filter !== "all" && item.dataset.group !== filter;
      });
    }));
  }

  async function pollRelay(config, articleId, state, onUpdate) {
    if (!config.liveRelay) {
      state.relayStatus("unavailable", "即時 relay 尚未設定；目前顯示歷史快照。", false);
      return;
    }
    let stopped = false;
    const run = async () => {
      if (stopped) return;
      try {
        const url = new URL(config.liveRelay);
        url.searchParams.set("article_id", articleId);
        url.searchParams.set("after_cursor", String(state.cursor));
        url.searchParams.set("limit", String(RELAY_LIMIT));
        const page = await fetchJson(url, 512 * 1024);
        if (!page || page.schema_version !== 1 || !Array.isArray(page.items)) throw new PublicDataError("relay page schema is incompatible");
        const items = page.items.map(validatePush);
        for (const push of items) {
          if (!Number.isSafeInteger(push.cursor) || push.cursor <= state.cursor) throw new PublicDataError("relay cursor is not monotonic");
          state.cursor = push.cursor;
          state.pushes.set(push.pushId, push);
        }
        onUpdate([...state.pushes.values()]);
        const stale = page.stale === true;
        state.relayStatus(stale ? "stale" : "fresh", stale ? "即時 relay 已過期，保留最後資料。" : "即時 relay 已連線。", stale);
      } catch (error) {
        state.relayStatus("stale", `即時 relay 暫時不可用（${error.name}）；保留最後資料。`, true);
      } finally {
        if (!stopped) state.timer = setTimeout(run, RELAY_POLL_MS);
      }
    };
    run();
    return () => { stopped = true; clearTimeout(state.timer); };
  }

  async function startPtt(config) {
    const pageStatus = document.querySelector("[data-ptt-status]");
    const relayStatus = document.querySelector("[data-relay-status]");
    const select = document.querySelector("[data-article-select]");
    const list = document.querySelector("[data-push-list]");
    const artifact = await loadPttArtifact(config.ptt);
    clear(select);
    artifact.articles.forEach((article) => select.append(articleOption(article)));
    if (!artifact.articles.length) {
      status(pageStatus, "unavailable", "公開 PTT 快照目前沒有文章。影片功能不受影響。 ");
      return;
    }
    let stopRelay = null;
    const show = async () => {
      if (stopRelay) stopRelay();
      const article = artifact.articles.find((item) => item.articleId === select.value) || artifact.articles[0];
      const state = {
        cursor: 0,
        pushes: new Map(article.pushes.map((push) => [push.pushId, push])),
        relayStatus: (kind, message) => status(relayStatus, kind, message),
        timer: null,
      };
      renderPushes(list, [...state.pushes.values()]);
      const incomplete = artifact.completeness !== "complete" || article.completeness !== "complete";
      status(pageStatus, incomplete ? "partial" : "complete", incomplete ? "歷史資料不完整；未出現的推文不可解讀為 0。" : "歷史資料完整。 ");
      stopRelay = await pollRelay(config, article.articleId, state, (pushes) => renderPushes(list, pushes));
    };
    select.addEventListener("change", show);
    await show();
  }

  async function startCustomView(config) {
    const form = document.querySelector("[data-live-sync-form]");
    const frame = document.querySelector("[data-live-player]");
    const message = document.querySelector("[data-live-status]");
    const pushes = document.querySelector("[data-live-pushes]");
    const params = new URLSearchParams(location.search);
    const input = form?.querySelector("input[name=stream]");
    if (input && params.get("stream")) input.value = params.get("stream");
    const load = async (event, supplied = null) => {
      event?.preventDefault();
      const raw = supplied ?? input?.value ?? params.get("stream") ?? "";
      const videoId = parseYouTubeId(raw);
      if (!videoId) {
        status(message, "unavailable", "請輸入有效的 YouTube 影片網址或 ID。 ");
        return;
      }
      embed(frame, videoId);
      status(message, "ready", "影片已初始化；PTT 不可用時仍可播放。 ");
      if (input) history.replaceState(null, "", `?stream=${encodeURIComponent(raw)}`);
      try {
        const artifact = await loadPttArtifact(config.ptt);
        const article = artifact.articles[0];
        if (article) renderPushes(pushes, article.pushes);
      } catch (error) {
        clear(pushes);
        pushes.append(element("p", "empty-note", `PTT 暫時不可用（${error.name}）。`));
      }
    };
    if (form) form.addEventListener("submit", load);
    const initial = input?.value || params.get("stream");
    if (initial) await load(null, initial);
  }

  function validateWatchalong(value) {
    if (!value || value.schema_version !== 1 || !Array.isArray(value.sessions)) throw new PublicDataError("Watchalong artifact schema is incompatible");
    isoTime(value.generated_at, "Watchalong generated_at");
    return value.sessions.map((raw) => ({
      sessionId: boundedString(raw.session_id, "session_id", 256, true),
      title: boundedString(raw.title, "session.title", 300, true),
      masterVideoId: parseYouTubeId(raw.master_video_id),
      sourceVideoId: raw.source_video_id == null ? null : parseYouTubeId(raw.source_video_id),
      sourceOffset: Number.isFinite(Number(raw.source_offset_seconds)) ? Number(raw.source_offset_seconds) : 0,
      pttArticleId: raw.ptt_article_id == null ? null : boundedString(raw.ptt_article_id, "ptt_article_id", 256, true),
      transcript: raw.transcript,
      translation: raw.translation,
    }));
  }

  function validateTranscriptArtifact(value) {
    if (!value || value.schema_version !== 1 || !Array.isArray(value.bundles)) throw new PublicDataError("transcript artifact schema is incompatible");
    isoTime(value.generated_at, "transcript generated_at");
    if (typeof value.complete !== "boolean") throw new PublicDataError("transcript completeness is invalid");
    return value.bundles.map((raw) => {
      if (!raw || !Array.isArray(raw.segments) || !Array.isArray(raw.translations)) throw new PublicDataError("transcript bundle is invalid");
      const segments = raw.segments.map((segment) => {
        const start = Number(segment.start_ms), end = Number(segment.end_ms);
        if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start) throw new PublicDataError("transcript cue time is invalid");
        return { segmentId: boundedString(segment.segment_id, "segment_id", 128, true), startMs: start, endMs: end, text: boundedString(segment.text, "segment.text", 8000, true) };
      });
      const translations = raw.translations.map((translation) => {
        if (!Array.isArray(translation.texts) || translation.texts.length !== segments.length) throw new PublicDataError("translation cardinality is invalid");
        return { targetLanguage: boundedString(translation.target_language, "target_language", 32, true), texts: translation.texts.map((item) => boundedString(item, "translation.text", 8000, true)) };
      });
      return { videoId: parseYouTubeId(raw.video_id), transcriptId: boundedString(raw.transcript_id, "transcript_id", 256, true), segments, translations };
    });
  }

  function renderTranscript(target, bundle) {
    clear(target);
    if (!bundle) { target.append(element("p", "empty-note", "字幕資料 unavailable；播放功能仍可使用。")); return; }
    const translation = bundle.translations[0];
    bundle.segments.forEach((segment, index) => {
      const cue = element("div", "subtitle-cue");
      const seconds = Math.floor(segment.startMs / 1000);
      cue.append(element("time", "subtitle-time", `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`));
      cue.append(element("span", "subtitle-text", translation?.texts[index] || segment.text));
      target.append(cue);
    });
  }

  async function startWatchalong(config) {
    const selector = document.querySelector("[data-watchalong-select]");
    const master = document.querySelector("[data-master-player]");
    const source = document.querySelector("[data-source-player]");
    const statusNode = document.querySelector("[data-watchalong-status]");
    const subtitle = document.querySelector("[data-subtitle]");
    const syncButton = document.querySelector("[data-manual-sync]");
    if (!config.watchalong) throw new PublicDataError("Watchalong artifact is not configured");
    const sessions = validateWatchalong(await fetchJson(config.watchalong));
    let transcriptBundles = [];
    if (config.transcripts) {
      try { transcriptBundles = validateTranscriptArtifact(await fetchJson(config.transcripts)); }
      catch (_) { transcriptBundles = []; }
    }
    clear(selector);
    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session.sessionId;
      option.textContent = session.title;
      selector.append(option);
    }
    const show = () => {
      const session = sessions.find((item) => item.sessionId === selector.value) || sessions[0];
      if (!session) {
        status(statusNode, "unavailable", "目前沒有可用的同時視聽資料。 ");
        return;
      }
      embed(master, session.masterVideoId);
      embed(source, session.sourceVideoId);
      source.hidden = !session.sourceVideoId;
      syncButton.disabled = !session.sourceVideoId;
      syncButton.dataset.offset = String(session.sourceOffset);
      const bundle = transcriptBundles.find((item) => item.videoId === session.masterVideoId);
      renderTranscript(subtitle, bundle);
      const mode = config.automaticFollowerPlayback ? "自動 follower policy 已啟用" : "自動 follower 預設關閉；使用手動同步";
      status(statusNode, "ready", `${mode}。`);
    };
    selector.addEventListener("change", show);
    syncButton.addEventListener("click", () => {
      status(statusNode, "ready", `手動同步要求已確認；來源 offset ${syncButton.dataset.offset || "0"} 秒。瀏覽器限制下請在播放器內手動定位。`);
    });
    show();
  }

  async function boot() {
    const globalStatus = document.querySelector("[data-cloud-status]");
    try {
      const config = await loadConfig();
      document.documentElement.dataset.environment = config.environment;
      status(globalStatus, config.environment.includes("fixture") ? "preview" : "ready", config.environment.includes("fixture") ? "PUBLIC PREVIEW · FIXTURE DATA" : "PUBLIC DATA · READ ONLY");
      const page = document.body.dataset.cloudPage;
      if (page === "home") await startHome(config);
      if (page === "ptt") await startPtt(config);
      if (page === "live-sync") await startCustomView(config);
      if (page === "watchalong") await startWatchalong(config);
    } catch (error) {
      status(globalStatus, "unavailable", `公開資料暫時不可用（${error.name}）`);
      const pageStatus = document.querySelector("[data-page-status]");
      status(pageStatus, "unavailable", "資料未發布、已損壞或版本不相容。影片與基本導覽仍可使用。 ");
    }
  }

  window.HoloViewerCloud = { PublicDataError, fetchJson, parseYouTubeId, validateConfig, validateHome, validatePush, validateTranscriptArtifact };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
