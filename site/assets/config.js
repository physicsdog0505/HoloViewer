window.HOLOVIEWER_CONFIG = Object.freeze({
  apiBase: "https://holoviewer-public-api.singlebagel.workers.dev",
  youtubeStaticBase: "https://holoviewer-youtube-static-assets.singlebagel.workers.dev",
  watchalongStaticBase: "https://holoviewer-watchalong-static-assets.singlebagel.workers.dev",
  vodSubtitleStaticBase: "https://holoviewer-vod-subtitles-static-assets.singlebagel.workers.dev",
  vodSubtitleAvailability: Object.freeze({
    base: "",
    indexPath: "/data/subtitles/index.json"
  }),
  dailyDigest: Object.freeze({
    base: "",
    pathTemplate: ""
  }),
  pttArchiveMonths: Object.freeze({
    "2026-01": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-01.json"
    }),
    "2026-02": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-02.json"
    }),
    "2026-03": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-03.json"
    }),
    "2026-04": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-04.json"
    }),
    "2026-05": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-05.json"
    }),
    "2026-06": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-06.json"
    }),
    "2026-07": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-07.json"
    }),
    "2026-08": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-08.json"
    }),
    "2026-09": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-pilot.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-09.json"
    }),
    "2026-10": Object.freeze({
      base: "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
      manifest: "/ptt/v1/manifests/static-assets-full-2026-10.json"
    })
  })
});
