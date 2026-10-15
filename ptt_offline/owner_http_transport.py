"""Single-attempt owner Publisher HTTP executor for the existing API Worker.

Off by default: cannot send anything without explicit one-shot opt-in and
owner-provided secret. Sends exactly one signed JSON POST; never retries.
Unknown ACK/network outcome is a hard failure (no checkpoint advancement).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .public_today_contract import ContractError

MAX_JSON_BYTES=65536
OWNER_API_HOST="holoviewer-public-api.singlebagel.workers.dev"

def owner_signed_http_executor(*, endpoint: str, secret: str, allow_write: bool=False,
                               opener=urlopen, clock_ms=None):
    if not allow_write:
        raise ContractError("owner one-shot write authorization required")
    u=urlparse(endpoint)
    if (u.scheme!="https" or u.netloc!=OWNER_API_HOST or u.username or u.password or
        u.fragment or u.query or u.path!="/private/ptt/publish"):
        raise ContractError("invalid owner Publisher endpoint")
    if not isinstance(secret,str) or len(secret)<32:
        raise ContractError("publisher HMAC secret unavailable")
    if clock_ms is None:
        clock_ms=lambda: int(time.time()*1000)

    def execute(batch):
        if not isinstance(batch,dict) or not 1<=len(batch.get("rows",[]))<=5:
            raise ContractError("invalid bounded Publisher batch")
        raw=json.dumps(batch,separators=(",",":"),ensure_ascii=False,sort_keys=True).encode("utf-8")
        if len(raw)>MAX_JSON_BYTES:
            raise ContractError("signed Publisher payload exceeds 64KiB")
        timestamp=str(clock_ms())
        signature=hmac.new(secret.encode("utf-8"),
            timestamp.encode("ascii")+b"\n"+raw,hashlib.sha256).hexdigest()
        request=Request(endpoint,data=raw,method="POST",headers={
            "Content-Type":"application/json",
            "X-Ptt-Timestamp":timestamp,
            "X-Ptt-Signature":signature,
        })
        # One call only; do not catch and retry uncertain remote commit.
        with opener(request,timeout=10) as response:
            if response.status!=200:
                raise ContractError("non-success publisher response; reconcile before replay")
            data=response.read(MAX_JSON_BYTES+1)
            if len(data)>MAX_JSON_BYTES:
                raise ContractError("oversized Publisher ACK")
            try:
                receipt=json.loads(data)
            except (UnicodeDecodeError,ValueError) as exc:
                raise ContractError("malformed Publisher ACK") from exc
            if not isinstance(receipt,dict):
                raise ContractError("invalid Publisher ACK body")
            return receipt
    return execute
