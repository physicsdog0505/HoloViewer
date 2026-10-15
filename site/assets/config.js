const localHost=/^(127\.0\.0\.1|localhost)$/.test(window.location.hostname);
window.HOLOVIEWER_CONFIG=Object.freeze({
 apiBase: localHost ? "/__api" : "https://holoviewer-public-api.singlebagel.workers.dev"
});
