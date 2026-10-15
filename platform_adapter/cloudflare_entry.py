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
        if parsed.path not in {"/", "/api/home", "/history", "/custom-view", "/custom-view/session", "/collab", "/collab/session", "/api/collab/live"}:
            return Response(
                "Public provider route not yet connected",
                status=503,
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Cache-Control": "no-store"},
            )

        # Import only the accepted product handler, never a cloned route table.
        # Packaging/import support must be proved on the actual Python Workers
        # runtime before this experimental entrypoint can be promoted.
        try:
            # Cloudflare/Pyodide uses async fetch. Accepted 4174 data loaders
            # remain synchronous but consume request-local preloaded values.
            # Cloudflare same-account workers.dev subrequests require a service binding.
            # Keep the old injectable transport for disposable offline fixture tests.
            api_service = getattr(getattr(self, "env", None), "PUBLIC_API", None)
            getter = partial(fetch_canonical_json, api_service=api_service)
            preload = await preload_for_accepted_request(target, getter)
            with preloaded_public_reads(preload):
                result = dispatch_accepted_get(
                    _accepted_handler(), target=target, method=str(request.method)
                )
        except PublicAPIUnavailable:
            return Response(
                "Public data temporarily unavailable", status=503,
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Cache-Control": "no-store"},
            )
        except Exception as exc:
            # Source-only local Pyodide feasibility: log exception identity, not
            # request URL, video IDs, API content or secrets. Never mask errors.
            print("PYTHON_WORKER_FEASIBILITY_EXCEPTION:",
                  type(exc).__module__, type(exc).__name__)
            raise
        # Header names/values come from the accepted handler. Do not return
        # hop-by-hop server transport headers to the Worker network stack.
        headers = {
            key: value
            for key, value in result.headers
            if key.lower() not in {"connection", "transfer-encoding", "server", "date", "content-length"}
        }
        return Response(result.body, status=result.status, headers=headers)
