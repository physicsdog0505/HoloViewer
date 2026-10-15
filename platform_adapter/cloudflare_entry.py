"""Experimental Cloudflare Python Worker fetch shell — source feasibility only.

Uses Cloudflare's official WorkerEntrypoint/Response interface. No Wrangler
binding, deployment, second Worker API, or product/router copy is created.

To execute inside Cloudflare, the build must package the immutable accepted
4174 modules, and the existing Python urllib/local SQLite dependencies must
be replaced at the *approved provider boundary*. Until then, do not deploy.
"""
from urllib.parse import urlsplit
from functools import partial

from workers import WorkerEntrypoint, Response
from platform_adapter.worker_transport import dispatch_accepted_get
from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable, preloaded_public_reads
from platform_adapter.worker_preload import preload_for_accepted_request, fetch_canonical_json
from platform_adapter.runtime_binding import bind_public_today
from platform_adapter.page_fallbacks import render_page_fallback
from platform_adapter.home_lightweight import dispatch_lightweight_home, build_request_live_rail
from platform_adapter.live_rail_binding import using_live_rail_html

PAGE_ROUTES = frozenset({
    "/", "/history", "/custom-view", "/custom-view/session",
    "/collab", "/collab/session", "/ptt-today",
    "/watchalong", "/watchalong/session",
})
PAGE_ONLY_FALLBACK_ROUTES = frozenset({"/ptt-today", "/watchalong", "/watchalong/session"})

_bound = False


def _accepted_handler():
    """Bind the one canonical provider before invoking original product routes."""
    global _bound
    import client_app
    if not _bound:
        bind_public_today(client_app, api_base=DEFAULT_API)
        _bound = True
    from platform_adapter.playback_routes import playback_handler
    return playback_handler(client_app.ClientRequestHandler)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed = urlsplit(str(request.url))
        if parsed.scheme not in {"http", "https"}:
            return Response("Invalid URL", status=400)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query

        # Reject non-GET requests before any upstream API fetch or product dispatch.
        if str(request.method) != "GET":
            return Response("Method Not Allowed", status=405,
                            headers={"Allow": "GET", "Cache-Control": "no-store"})

        # Keep the accepted iframe footprint while #48 PTT is not connected.
        # Only the embedded reader is blank; standalone PTT remains gated.
        if (parsed.path == "/ptt-today"
                and "focus=1" in parsed.query.split("&")
                and "embed=1" in parsed.query.split("&")):
            return Response("", status=200,
                            headers={"Content-Type": "text/html; charset=utf-8",
                                     "Cache-Control": "no-store"})

        # Phase-E first proof slice only. Unbound routes must never fall back
        # to the immutable product's local SQLite/file loaders in a Worker.
        # This is a data-readiness gate, NOT another product route dispatcher.
        if parsed.path not in PAGE_ROUTES | {"/api/home", "/api/collab/live"}:
            return Response(
                "Public provider route not yet connected",
                status=503,
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Cache-Control": "no-store"},
            )

        # Page-first contract: pages whose providers are not wired yet still
        # render the accepted 4174 UI shell. Data APIs remain independently gated.
        if parsed.path in PAGE_ONLY_FALLBACK_ROUTES:
            fallback = render_page_fallback(target)
            if fallback is not None:
                status, html = fallback
                return Response(
                    html, status=status,
                    headers={"Content-Type": "text/html; charset=utf-8",
                             "Cache-Control": "no-store"},
                )

        # Import only the accepted product handler, never a cloned route table.
        # Packaging/import support must be proved on the actual Python Workers
        # runtime before this experimental entrypoint can be promoted.
        stage = "preload"
        try:
            # Cloudflare/Pyodide uses async fetch. Accepted 4174 data loaders
            # remain synchronous but consume request-local preloaded values.
            # Cloudflare same-account workers.dev subrequests require a service binding.
            # Keep the old injectable transport for disposable offline fixture tests.
            api_service = getattr(getattr(self, "env", None), "PUBLIC_API", None)
            getter = partial(fetch_canonical_json, api_service=api_service)
            preload = await preload_for_accepted_request(target, getter)
            with preloaded_public_reads(preload):
                if parsed.path in {"/", "/api/home"}:
                    stage = "home-render"
                    result = dispatch_lightweight_home(target)
                else:
                    stage = "live-rail"
                    rail_html = build_request_live_rail() if ("/v1/catalog/today", ()) in preload else ""
                    with using_live_rail_html(rail_html):
                        stage = "accepted-dispatch"
                        result = dispatch_accepted_get(
                            _accepted_handler(), target=target, method=str(request.method)
                        )
        except PublicAPIUnavailable:
            if parsed.path in PAGE_ROUTES:
                fallback = render_page_fallback(target)
                if fallback is not None:
                    status, html = fallback
                    return Response(
                        html, status=status,
                        headers={"Content-Type": "text/html; charset=utf-8",
                                 "Cache-Control": "no-store"},
                    )
            return Response(
                "Public data temporarily unavailable", status=503,
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Cache-Control": "no-store"},
            )
        except Exception as exc:
            # Never surface an ordinary Python exception as a Cloudflare 1101
            # for a user-facing page. Log only exception identity, then fall
            # back to the accepted 4174 page-first shell. Data APIs remain
            # explicit failures and are never fabricated.
            print("PYTHON_WORKER_PAGE_EXCEPTION:",
                  stage, type(exc).__module__, type(exc).__name__)
            if parsed.path in PAGE_ROUTES:
                try:
                    fallback = render_page_fallback(target)
                except Exception as fallback_exc:
                    print("PYTHON_WORKER_FALLBACK_EXCEPTION:",
                          type(fallback_exc).__module__, type(fallback_exc).__name__)
                    fallback = None
                if fallback is not None:
                    status, html = fallback
                    return Response(
                        html, status=status,
                        headers={"Content-Type": "text/html; charset=utf-8",
                                 "Cache-Control": "no-store",
                                 "X-HoloViewer-Recovered-Stage": stage},
                    )
            return Response(
                "Public page temporarily unavailable",
                status=503,
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Cache-Control": "no-store",
                         "X-HoloViewer-Recovered-Stage": stage},
            )
        # Header names/values come from the accepted handler. Do not return
        # hop-by-hop server transport headers to the Worker network stack.
        headers = {
            key: value
            for key, value in result.headers
            if key.lower() not in {"connection", "transfer-encoding", "server", "date", "content-length"}
        }
        return Response(result.body, status=result.status, headers=headers)
