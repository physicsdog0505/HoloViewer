"""Single-attempt owner Publisher HTTP executors for the existing API Worker.

Off by default: cannot send anything without explicit owner opt-in and
owner-provided secret. Publish and reconcile both send exactly one signed JSON
POST. Neither path performs an internal retry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import socket
import time
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .public_today_contract import ContractError

MAX_JSON_BYTES=131072
OWNER_API_HOST="holoviewer-public-api.singlebagel.workers.dev"
BROWSER_USER_AGENT="Mozilla/5.0"

class RemoteOutcomeUnknown(RuntimeError):
    """The publish request may or may not have committed remotely."""

class ReconcileUnavailable(RuntimeError):
    """Read-only remote reconciliation could not be completed."""

def _validate_endpoint(endpoint,path):
    u=urlparse(endpoint)
    if (u.scheme!="https" or u.netloc!=OWNER_API_HOST or u.username or u.password or
        u.fragment or u.query or u.path!=path):
        raise ContractError("invalid owner Publisher endpoint")

def _signed_post_executor(*,endpoint,secret,path,allow_write=False,opener=urlopen,
                          clock_ms=None,max_rows=25,max_bytes=MAX_JSON_BYTES,
                          reconcile=False):
    if not allow_write:
        raise ContractError("owner one-shot write authorization required")
    _validate_endpoint(endpoint,path)
    if not isinstance(secret,str) or len(secret)<32:
        raise ContractError("publisher HMAC secret unavailable")
    if type(max_rows) is not int or not 1<=max_rows<=25 or type(max_bytes) is not int or not 1<=max_bytes<=MAX_JSON_BYTES:
        raise ContractError("invalid bounded Publisher transport limits")
    if clock_ms is None:
        clock_ms=lambda: int(time.time()*1000)

    def execute(batch):
        if not isinstance(batch,dict) or not 1<=len(batch.get("rows",[]))<=max_rows:
            raise ContractError("invalid bounded Publisher batch")
        raw=json.dumps(batch,separators=(",",":"),ensure_ascii=False,sort_keys=True).encode("utf-8")
        if len(raw)>max_bytes:
            raise ContractError("signed Publisher payload exceeds configured bound")
        timestamp=str(clock_ms())
        signature=hmac.new(secret.encode("utf-8"),
            timestamp.encode("ascii")+b"\n"+raw,hashlib.sha256).hexdigest()
        request=Request(endpoint,data=raw,method="POST",headers={
            "Content-Type":"application/json",
            "User-Agent":BROWSER_USER_AGENT,
            "X-Ptt-Timestamp":timestamp,
            "X-Ptt-Signature":signature,
        })
        try:
            with opener(request,timeout=60) as response:
                status=response.status
                data=response.read(MAX_JSON_BYTES+1)
        except HTTPError as exc:
            if reconcile:
                raise ReconcileUnavailable(f"reconcile HTTP {exc.code}") from exc
            if exc.code==409:
                raise RemoteOutcomeUnknown("publisher returned reconcile_required") from exc
            raise RemoteOutcomeUnknown(f"publisher HTTP {exc.code}") from exc
        except (RemoteDisconnected,URLError,TimeoutError,socket.timeout,ConnectionError,OSError) as exc:
            if reconcile:
                raise ReconcileUnavailable(type(exc).__name__) from exc
            raise RemoteOutcomeUnknown(type(exc).__name__) from exc
        if len(data)>MAX_JSON_BYTES:
            if reconcile:
                raise ReconcileUnavailable("oversized reconcile response")
            raise RemoteOutcomeUnknown("oversized Publisher ACK")
        try:
            receipt=json.loads(data)
        except (UnicodeDecodeError,ValueError) as exc:
            if reconcile:
                raise ReconcileUnavailable("malformed reconcile response") from exc
            raise RemoteOutcomeUnknown("malformed Publisher ACK") from exc
        if not isinstance(receipt,dict):
            if reconcile:
                raise ReconcileUnavailable("invalid reconcile response")
            raise RemoteOutcomeUnknown("invalid Publisher ACK body")
        if status!=200:
            if reconcile:
                raise ReconcileUnavailable(f"reconcile HTTP {status}")
            raise RemoteOutcomeUnknown(f"publisher HTTP {status}")
        return receipt
    return execute

def owner_signed_http_executor(*, endpoint: str, secret: str, allow_write: bool=False,
                               opener=urlopen, clock_ms=None, max_rows=5, max_bytes=65536):
    return _signed_post_executor(endpoint=endpoint,secret=secret,
        path="/private/ptt/publish",allow_write=allow_write,opener=opener,
        clock_ms=clock_ms,max_rows=max_rows,max_bytes=max_bytes,reconcile=False)

def owner_signed_reconcile_executor(*, endpoint: str, secret: str, allow_write: bool=False,
                                    opener=urlopen, clock_ms=None, max_rows=25,
                                    max_bytes=MAX_JSON_BYTES):
    return _signed_post_executor(endpoint=endpoint,secret=secret,
        path="/private/ptt/reconcile",allow_write=allow_write,opener=opener,
        clock_ms=clock_ms,max_rows=max_rows,max_bytes=max_bytes,reconcile=True)
