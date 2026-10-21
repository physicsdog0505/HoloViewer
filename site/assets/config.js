window.HOLOVIEWER_CONFIG = Object.freeze({
  apiBase: "https://holoviewer-public-api.singlebagel.workers.dev",
  pttArchiveMonths: Object.freeze({
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
