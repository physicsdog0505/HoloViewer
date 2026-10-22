#!/usr/bin/env python3
"""Export the three approved 8501 Watchalong records as static Public assets.

The exporter is deliberately read-only with respect to the private source.  It
validates every pinned identity before writing browser-facing JSON and never
imports a provider client or opens a network connection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PLAYLIST_ID = "PL12UaAf_xzfozU6PKHlOwbskdUTFKnGrK"
SCHEMA = "holoviewer-watchalong-event-v1"
MANIFEST_SCHEMA = "holoviewer-watchalong-manifest-v1"

SESSIONS: tuple[dict[str, Any], ...] = (
    {
        "master": "eFYByyw5AJc",
        "day": "2026-10-01",
        "title": "【初見】『無職転生~異世界行ったら本気だす~』同時視聴【ホロライブ/兎田ぺこら】",
        "playlist_start": 1,
        "sources": ("qwL78s9afLk", "vqzPu11Haa4", "J-mcCv64_CA", "V-99ULU904Q", "IglYIVE5XhI", "EKFVL38awRc"),
        "starts_ms": (608767, 2095935, 3568000, 5025000, 6488000, 8028500),
        "transcript_id": "5b5424cd70f9cc99561e768222fe501b746d7f0572765eba5b958f02583d298d",
        "transcript_hash": "f67ce6dd021ed9bddd9af2fcadddddab029dbafdb9d3763e4abeb71d8aded456",
        "cue_count": 1568,
        "translation_kind": "corpus-artifact",
        "translation_id": "db98d96002931734b6336c01732b6d981fbee3ed71a5304352c37f7ec4a92168",
        "translation_rel": "data/watchalong/transcripts/youtube/eFYByyw5AJc/translations/db98d96002931734b6336c01732b6d981fbee3ed71a5304352c37f7ec4a92168.json",
        "translation_quality": "quality-v2-complete",
        "breakpoint_status": "REPAIRED",
        "breakpoint_note": "Excluded the adjacent session's repeated episode-7 source and one 79-second false-positive cue; retained the six cadence-consistent source starts.",
    },
    {
        "master": "U2o13h1Oib4",
        "day": "2026-10-08",
        "title": "#2【初見】『無職転生~異世界行ったら本気だす~』同時視聴【ホロライブ/兎田ぺこら】",
        "playlist_start": 7,
        "sources": ("Vr0pc63j7jw", "vPuCpo-Fnec", "WEGsI-c1MW0", "0vzm32_8d1A", "hlX2iIyswnE", "4Gdgruo7pAk"),
        "starts_ms": (728920, 2205800, 3689039, 5141960, 6606639, 8088040),
        "transcript_id": "834768fb940b919369e2dc666e29f718dca12323f11e23de3670197e77de4323",
        "transcript_hash": "747b93b56889947242869a3b049c89560dc1e2f9028e9e255c8167c01ae72023",
        "cue_count": 1438,
        "translation_kind": "corpus-artifact",
        "translation_id": "e99ab40eac7c633a8d658854ef6e506e2f2d48ca9dcddd808b73c059bc29574b",
        "translation_rel": "data/watchalong/transcripts/youtube/U2o13h1Oib4/translations/e99ab40eac7c633a8d658854ef6e506e2f2d48ca9dcddd808b73c059bc29574b.json",
        "translation_quality": "quality-v2-complete",
        "breakpoint_status": "PRESENT",
        "breakpoint_note": "Six high-confidence starts from the accepted 8501 transcript cue pipeline.",
    },
    {
        "master": "8pF4qHcshDc",
        "day": "2026-10-15",
        "title": "#3【初見】『無職転生~異世界行ったら本気だす~』同時視聴【ホロライブ/兎田ぺこら】",
        "playlist_start": 13,
        "sources": ("hyeZXJuE-gk", "C8QHUmB9y-8", "Kv_z05UQXbs", "tcYAfUkrvJ8", "UOsw-ih3CMw", "oJiaPS91-9U"),
        "starts_ms": (737920, 2208560, 3689720, 5156239, 6612880, 8150599),
        "transcript_id": "b6d2a1b14817e07fb4fca4d21ca2911392c652e23ee8235b116432af32205cd2",
        "transcript_hash": "c7a36360c63c0fb9122bbb12a9684f90cf018682dfd0df89771e8c859ce049d0",
        "cue_count": 1461,
        "translation_kind": "corpus-artifact",
        "translation_id": "5084c85ae7ab6ff37a9e586252f8efc365be85bf723c5fb5d6a3ddb3b01a112f",
        "translation_rel": "data/watchalong/transcripts/youtube/8pF4qHcshDc/translations/5084c85ae7ab6ff37a9e586252f8efc365be85bf723c5fb5d6a3ddb3b01a112f.json",
        "translation_quality": "quality-v2-complete",
        "breakpoint_status": "PRESENT",
        "breakpoint_note": "Six high-confidence starts from the selected 8501 public-caption transcript.",
    },
)


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_mapping(source_root: Path) -> dict[str, dict[str, Any]]:
    db = source_root / "data/watchalong/watchalong_archive.sqlite3"
    connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute(
            "SELECT master_identity, playlist_url, playlist_start_index, source_urls_json "
            "FROM watchalong_source_mappings"
        ).fetchall()
    finally:
        connection.close()
    result: dict[str, dict[str, Any]] = {}
    for master, playlist, start, sources_json in rows:
        result[str(master)] = {
            "playlist": str(playlist),
            "start": int(start),
            "sources": tuple(_youtube_id(value) for value in json.loads(sources_json)),
        }
    return result


def _youtube_id(value: str) -> str:
    for marker in ("v=", "youtu.be/"):
        if marker in value:
            value = value.split(marker, 1)[1]
            break
    return value.split("&", 1)[0].split("?", 1)[0].split("/", 1)[0]


def transcript_paths(source_root: Path, session: dict[str, Any]) -> tuple[Path, Path]:
    base = source_root / "data/watchalong/transcripts/youtube" / session["master"] / "transcripts" / session["transcript_id"]
    return base / "metadata.json", base / "segments.json"


def validate_segments(session: dict[str, Any], metadata: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    expected = {
        "video_id": session["master"],
        "transcript_id": session["transcript_id"],
        "content_hash": session["transcript_hash"],
        "segment_count": session["cue_count"],
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"{session['master']} transcript {key} mismatch")
    if len(rows) != session["cue_count"]:
        raise ValueError(f"{session['master']} cue count mismatch")
    cue_ids: set[str] = set()
    last_start = -1
    for index, row in enumerate(rows):
        cue_id = str(row.get("segment_id", ""))
        start, end = row.get("start_ms"), row.get("end_ms")
        if not cue_id or cue_id in cue_ids:
            raise ValueError(f"{session['master']} invalid cue id at {index}")
        if not isinstance(start, int) or not isinstance(end, int) or start < last_start or end <= start:
            raise ValueError(f"{session['master']} invalid cue timing at {index}")
        if not str(row.get("source_text", "")).strip():
            raise ValueError(f"{session['master']} empty source cue at {index}")
        cue_ids.add(cue_id)
        last_start = start


def checkpoint_identity(rows: list[dict[str, Any]]) -> str:
    payload = {
        "source": [[row["start_ms"], row["end_ms"], row["source_text"], "manual-paste"] for row in rows],
        "provider": "gemini:gemini-3.5-flash-lite",
        "target_language": "zh-TW",
        "max_segments": 20,
        "max_chars": 2000,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())


def load_translations(source_root: Path, session: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    artifact = read_json(source_root / session["translation_rel"])
    if session["translation_kind"] == "resumable-checkpoint":
        if checkpoint_identity(rows) != session["translation_id"] or artifact.get("identity") != session["translation_id"]:
            raise ValueError(f"{session['master']} checkpoint identity mismatch")
        batches = artifact.get("batches")
        if artifact.get("status") != "ready" or not isinstance(batches, list):
            raise ValueError(f"{session['master']} checkpoint is not ready")
        translations: list[str] = []
        cursor = 0
        for batch in batches:
            values = batch.get("translations")
            if batch.get("status") != "ready" or batch.get("start") != cursor or batch.get("end") != cursor + len(values or []):
                raise ValueError(f"{session['master']} checkpoint coverage gap")
            translations.extend(values)
            cursor = int(batch["end"])
    else:
        identity = artifact.get("identity") or {}
        if artifact.get("artifact_id") != session["translation_id"]:
            raise ValueError(f"{session['master']} translation artifact mismatch")
        if identity.get("transcript_hash") != session["transcript_hash"]:
            raise ValueError(f"{session['master']} translation fingerprint mismatch")
        translations = artifact.get("translations")
    if not isinstance(translations, list) or len(translations) != len(rows):
        raise ValueError(f"{session['master']} translation coverage mismatch")
    if any(not isinstance(value, str) or not value.strip() for value in translations):
        raise ValueError(f"{session['master']} contains an empty translation")
    return [value.strip() for value in translations]


def build_event(source_root: Path, session: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    metadata_path, segments_path = transcript_paths(source_root, session)
    metadata, rows = read_json(metadata_path), read_json(segments_path)
    if not isinstance(metadata, dict) or not isinstance(rows, list):
        raise ValueError(f"{session['master']} malformed transcript files")
    validate_segments(session, metadata, rows)
    translations = load_translations(source_root, session, rows)

    if mapping["start"] != session["playlist_start"] or not str(mapping["playlist"]).endswith(PLAYLIST_ID):
        raise ValueError(f"{session['master']} source mapping mismatch")
    if mapping["sources"][: len(session["sources"])] != session["sources"]:
        raise ValueError(f"{session['master']} source sequence mismatch")
    if session["master"] == "eFYByyw5AJc" and mapping["sources"][6:] != ("Vr0pc63j7jw",):
        raise ValueError("eFYByyw5AJc repaired boundary evidence changed")
    if len(session["sources"]) != len(session["starts_ms"]):
        raise ValueError(f"{session['master']} breakpoint/source cardinality mismatch")

    subtitles = [
        {
            "cue_id": row["segment_id"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "start_seconds": row["start_ms"] / 1000,
            "end_seconds": row["end_ms"] / 1000,
            "original": row["source_text"],
            "translation": translations[index],
        }
        for index, row in enumerate(rows)
    ]
    sync_payload = [
        {
            "segment_id": f"episode-{index + 1:02d}",
            "label": f"第 {session['playlist_start'] + index} 集",
            "host_start_ms": start,
            "host_start_seconds": start / 1000,
            "source_start_ms": 0,
            "source_start_seconds": 0,
            "source_video_id": source,
        }
        for index, (source, start) in enumerate(zip(session["sources"], session["starts_ms"], strict=True))
    ]
    return {
        "schema_version": SCHEMA,
        "event_id": session["master"],
        "session_day": session["day"],
        "title": session["title"],
        "master_video_id": session["master"],
        "playlist_id": PLAYLIST_ID,
        "playlist_start_index": session["playlist_start"],
        "source_video_ids": list(session["sources"]),
        "subtitle_timeline": "host",
        "segments": sync_payload,
        "subtitles": subtitles,
        "artifacts": {
            "transcript": {
                "transcript_id": session["transcript_id"],
                "content_hash": session["transcript_hash"],
                "cue_count": session["cue_count"],
                "source": f"TranscriptCorpus/youtube/{session['master']}/{session['transcript_id']}",
            },
            "translation": {
                "artifact_id": session["translation_id"],
                "transcript_hash": session["transcript_hash"],
                "coverage": "COMPLETE",
                "quality": session["translation_quality"],
                "translated_cues": len(translations),
                "source": session["translation_rel"],
            },
            "sync": {
                "identity": sha256(canonical_bytes(sync_payload)),
                "status": session["breakpoint_status"],
                "note": session["breakpoint_note"],
                "source": "data/watchalong/watchalong_archive.sqlite3#watchalong_source_mappings",
            },
        },
        "completeness": {
            "transcript": "COMPLETE",
            "translation": "COMPLETE",
            "sync": session["breakpoint_status"],
        },
    }


def export(source_root: Path, output_root: Path, *, check: bool) -> None:
    mappings = load_mapping(source_root)
    if set(item["master"] for item in SESSIONS) - set(mappings):
        raise ValueError("one or more pinned source mappings are unavailable")
    event_dir = output_root / "events"
    outputs: dict[Path, bytes] = {}
    manifest_events: list[dict[str, Any]] = []
    for session in SESSIONS:
        event = build_event(source_root, session, mappings[session["master"]])
        data = canonical_bytes(event)
        relative = Path("events") / f"{session['master']}.json"
        outputs[output_root / relative] = data
        manifest_events.append({
            "event_id": session["master"],
            "session_day": session["day"],
            "title": session["title"],
            "master_video_id": session["master"],
            "source_video_id": session["sources"][0],
            "source_count": len(session["sources"]),
            "cue_count": session["cue_count"],
            "transcript_hash": session["transcript_hash"],
            "translation_artifact_id": session["translation_id"],
            "translation_status": "COMPLETE",
            "path": "/data/watchalong/" + relative.as_posix(),
            "sha256": sha256(data),
        })
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "generated_from": "8501 read-only artifacts",
        "event_count": len(manifest_events),
        "events": manifest_events,
    }
    outputs[output_root / "manifest.json"] = canonical_bytes(manifest)

    expected = {output_root / "manifest.json", *(output_root / "events" / f"{item['master']}.json" for item in SESSIONS)}
    if check:
        for path, data in outputs.items():
            if not path.exists() or path.read_bytes() != data:
                raise ValueError(f"generated asset differs: {path}")
        extras = set(event_dir.glob("*.json")) - (expected - {output_root / "manifest.json"})
        if extras:
            raise ValueError(f"unexpected exported events: {sorted(str(path) for path in extras)}")
        return

    event_dir.mkdir(parents=True, exist_ok=True)
    for path, data in outputs.items():
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("site/data/watchalong"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        export(args.source_root.resolve(), args.output_root.resolve(), check=args.check)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"watchalong export failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
