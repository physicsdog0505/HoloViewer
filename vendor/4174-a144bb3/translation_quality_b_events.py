"""Fail-closed local B stage event journal, without prompts or result text."""
from __future__ import annotations
import json
import os
import fcntl
from datetime import datetime, timezone
from pathlib import Path

def _safe_http_status(exc):
    if exc is None:
        return None
    queue = [exc]
    seen = set()
    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        for attr in ("status_code", "code", "http_status"):
            try:
                code = getattr(current, attr, None)
            except Exception:
                code = None
            if type(code) is int and 100 <= code <= 599:
                return code
        for attr in ("__cause__", "__context__"):
            nested = getattr(current, attr, None)
            if isinstance(nested, BaseException):
                queue.append(nested)
    return None


def _safe_provider_status(exc):
    """Return a small provider status token, never an arbitrary error message."""
    if exc is None:
        return None
    allowed = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED",
               "PERMISSION_DENIED", "UNAUTHENTICATED", "INVALID_ARGUMENT",
               "INTERNAL", "UNKNOWN"}
    queue, seen = [exc], set()
    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        for attr in ("status", "reason"):
            try:
                value = getattr(current, attr, None)
            except Exception:
                value = None
            if hasattr(value, "name"):
                value = value.name
            if isinstance(value, str):
                token = value.strip().upper()
                if token in allowed:
                    return token
        for attr in ("__cause__", "__context__"):
            nested = getattr(current, attr, None)
            if isinstance(nested, BaseException):
                queue.append(nested)
    return None


EVENTS = frozenset({
    "sentence_intent_saved", "sentence_translation_ready", "retime_complete",
    "checkpoint_saved", "pending_cleared", "stage_reserved",
    "stage_dispatched", "stage_response_received", "stage_receipt_saved", "stage_ledger_saved",
    "stage_failed", "sentence_failed", "job_failed",
})

def append_event(folder, fingerprint, *, event, sentence_index=None, stage=None, error=None):
    if event not in EVENTS or not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("Invalid B journal event")
    root = Path(folder)
    if root.is_symlink():
        raise ValueError("Unsafe B event directory")
    root.mkdir(parents=True, exist_ok=True)
    target = root / (fingerprint + ".events.jsonl")
    if target.is_symlink():
        raise ValueError("Unsafe B event journal")
    location = None
    if error is not None and getattr(error, "__traceback__", None):
        from traceback import extract_tb
        frames = extract_tb(error.__traceback__)
        if frames:
            last = frames[-1]
            location = f"{Path(last.filename).name}:{last.lineno} ({last.name})"
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "sentence_index": sentence_index,
        "stage": stage,
        "error_class": type(error).__name__ if error is not None else None,
        "http_status": _safe_http_status(error),
        "provider_status": _safe_provider_status(error),
        "error_location": location,
    }
    encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)

def read_events(folder, fingerprint, *, limit=250):
    file = Path(folder) / (fingerprint + ".events.jsonl")
    if file.is_symlink():
        raise ValueError("Unsafe B event journal")
    if not file.exists():
        return []
    if file.stat().st_size > 4_000_000:
        raise ValueError("Oversized B event journal")
    records = []
    for line in file.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            records.append({"event": "incomplete_event_record"})
            continue
        if isinstance(entry, dict):
            records.append({key: entry.get(key) for key in ("at", "event", "sentence_index", "stage", "error_class", "error_location", "http_status", "provider_status")})
    return records

RUN_PHASES = frozenset({"source_check", "transcript_acquire", "a_check", "a_submit",
                       "a_wait", "b_provenance", "b_resume", "b_complete", "failed"})

def append_run_event(video_id, phase, *, error=None, upstream_type=None):
    """Pre-checkpoint B job evidence. No private transcript or provider response."""
    import re
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid video ID")
    if phase not in RUN_PHASES:
        raise ValueError("Invalid phase")
    from translation_fansub_capture import private_capture_root
    root = private_capture_root().parent / "b-run-events"
    if root.is_symlink():
        raise ValueError("Unsafe run event path")
    root.mkdir(parents=True, exist_ok=True)
    target = root / (video_id + ".jsonl")
    if target.is_symlink():
        raise ValueError("Unsafe run journal")
    location = None
    if error is not None and getattr(error, "__traceback__", None):
        import traceback
        frames=traceback.extract_tb(error.__traceback__)
        if frames:
            frame=frames[-1]
            location=f"{Path(frame.filename).name}:{frame.lineno}"
    import re
    safe_upstream = upstream_type if isinstance(upstream_type, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,89}", upstream_type) else None
    record={"at":datetime.now(timezone.utc).isoformat(),"phase":phase,
            "upstream_type": safe_upstream,
            "error_class":type(error).__name__ if error is not None else None,
            "http_status":_safe_http_status(error),
            "provider_status":_safe_provider_status(error),
            "location":location}
    fd=os.open(target, os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        os.write(fd,(json.dumps(record,sort_keys=True)+"\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)

def read_run_events(video_id, *, limit=100, root=None):
    import re
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid video ID")
    from translation_fansub_capture import private_capture_root
    folder = Path(root) if root is not None else private_capture_root().parent/"b-run-events"
    if folder.is_symlink():
        raise ValueError("Unsafe B run events directory")
    file=folder/(video_id+".jsonl")
    if file.is_symlink():
        raise ValueError("Unsafe run events path")
    if not file.exists():
        return []
    if file.stat().st_size>2_000_000:
        raise ValueError("Oversized run journal")
    result=[]
    for line in file.read_text().splitlines()[-limit:]:
        try:
            obj=json.loads(line)
        except json.JSONDecodeError:
            result.append({"phase":"truncated_record"})
            continue
        if isinstance(obj,dict):
            result.append({k:obj.get(k) for k in ("at","phase","error_class","location","http_status","provider_status","upstream_type")})
    return result
