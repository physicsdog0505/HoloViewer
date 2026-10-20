from __future__ import annotations

from collections import Counter, defaultdict

from .common import content_hash, taipei_day, validate_day


def _youtube(day: str, snapshot: dict) -> dict:
    available = snapshot.get("available") is True
    expected = snapshot.get("expected_ids")
    authority = snapshot.get("expected_authority") if isinstance(snapshot.get("expected_authority"), dict) else {}
    expected_known = (available and isinstance(expected, list) and authority.get("verified") is True
                      and authority.get("day") == day and isinstance(authority.get("version"), str)
                      and bool(authority.get("version")))
    rows = snapshot.get("rows") if available and isinstance(snapshot.get("rows"), list) else []
    actual, uncertain, delayed = [], [], []
    for row in rows:
        video_id = row.get("video_id")
        start = row.get("actual_start")
        if not isinstance(video_id, str) or not video_id:
            uncertain.append("invalid-video-identity")
            continue
        # A cross-midnight stream belongs wholly to the Taipei day on which it actually started.
        if not start:
            if row.get("scheduled_start") and taipei_day(row["scheduled_start"]) == day:
                uncertain.append(video_id)
            continue
        if taipei_day(start) != day:
            continue
        actual.append(video_id)
        if row.get("lifecycle_state") == "ended" and not row.get("actual_end"):
            delayed.append(video_id)
        if row.get("metadata_complete") is False:
            delayed.append(video_id)
    duplicates = sorted(k for k, n in Counter(actual).items() if n > 1)
    actual_set = sorted(set(actual))
    missing = sorted(set(expected or []) - set(actual_set)) if expected_known else []
    if not available or not expected_known:
        status = "UNKNOWN"
    elif duplicates or missing or delayed or uncertain:
        status = "REPAIR_NEEDED"
    else:
        status = "COMPLETE"
    return {"date": day, "source": "youtube", "expected_set": sorted(set(expected)) if expected_known else None,
            "actual_set": actual_set, "missing_ids": missing, "duplicates": duplicates,
            "unconfirmed_ids": sorted(set(uncertain)), "metadata_delayed_ids": sorted(set(delayed)),
            "completeness_status": status, "last_updated_at": snapshot.get("last_updated_at"),
            "source_version": snapshot.get("source_version"), "expected_authority": authority or None,
            "contract_gaps": list(snapshot.get("contract_gaps", []))}


def _ptt(day: str, snapshot: dict) -> dict:
    available = snapshot.get("available") is True
    expected = snapshot.get("expected_aids")
    authority = snapshot.get("expected_authority") if isinstance(snapshot.get("expected_authority"), dict) else {}
    expected_known = (available and isinstance(expected, list) and authority.get("verified") is True
                      and authority.get("day") == day and isinstance(authority.get("version"), str)
                      and bool(authority.get("version")))
    rows = snapshot.get("rows") if available and isinstance(snapshot.get("rows"), list) else []
    by_aid, keys = defaultdict(list), []
    for row in rows:
        if row.get("day") != day:
            continue
        aid, line = row.get("aid"), row.get("source_line")
        if isinstance(aid, str) and aid and type(line) is int and line > 0:
            by_aid[aid].append(line)
            keys.append(f"{aid}:{line}")
    duplicates = sorted(k for k, n in Counter(keys).items() if n > 1)
    gaps, unconfirmed = {}, []
    coverage = snapshot.get("coverage") if isinstance(snapshot.get("coverage"), dict) else {}
    for aid in sorted(set(expected or []) | set(by_aid)):
        lines = sorted(set(by_aid[aid]))
        proof = coverage.get(aid) if isinstance(coverage.get(aid), dict) else {}
        if proof.get("complete") is not True:
            unconfirmed.append(aid)
            continue
        start, end = proof.get("start_line"), proof.get("end_line")
        if type(start) is not int or type(end) is not int or start != 1 or end < start:
            unconfirmed.append(aid)
            continue
        missing_lines = sorted(set(range(start, end + 1)) - set(lines) - set(proof.get("non_push_lines", [])))
        if missing_lines:
            gaps[aid] = missing_lines
    missing_aids = sorted(set(expected or []) - set(by_aid)) if expected_known else []
    if not available or not expected_known:
        status = "UNKNOWN"
    elif duplicates or gaps or missing_aids or unconfirmed:
        status = "REPAIR_NEEDED"
    else:
        status = "COMPLETE"
    return {"date": day, "source": "ptt", "expected_set": sorted(set(expected)) if expected_known else None,
            "actual_set": sorted(by_aid), "missing_ids": missing_aids, "source_line_gaps": gaps,
            "duplicates": duplicates, "unconfirmed_ids": sorted(set(unconfirmed)),
            "completeness_status": status, "last_updated_at": snapshot.get("last_updated_at"),
            "source_version": snapshot.get("source_version"), "expected_authority": authority or None,
            "checkpoint": snapshot.get("checkpoint"), "manifest": snapshot.get("manifest"),
            "contract_gaps": list(snapshot.get("contract_gaps", []))}


def build_inventory(day: str, snapshot: dict) -> dict:
    validate_day(day)
    result = {"schema_version": "holoviewer-daily-inventory-v1", "date": day,
              "sources": [_youtube(day, snapshot.get("youtube", {})), _ptt(day, snapshot.get("ptt", {}))]}
    result["inventory_hash"] = content_hash(result)
    return result
