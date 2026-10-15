"""Safe bridge from existing VOD transcript/Gemini cache to the private lab.

Only explicit acquisition may contact a public YouTube caption provider.
Inspect/load are local read-only, never execute Gemini.
"""
from __future__ import annotations
import re

from archive_translation_service import ArchiveTranslationService
from frontend_time import youtube_video_id


def inspect_existing(video_url: str, *, service=None):
    video_id = video_url if isinstance(video_url,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',video_url) else youtube_video_id(video_url)
    if not video_id or len(video_id)!=11:
        raise ValueError("Invalid YouTube URL")
    service = service or ArchiveTranslationService()
    state=service.inspect(f"https://www.youtube.com/watch?v={video_id}")
    if state.record is None:
        return {"status":"missing_transcript","ja":[],"a":[],
                "source_video_id":video_id,"transcript_hash":None,"a_cached":False}
    record=state.record
    ja=[{"start_ms":int(c.start_ms),"end_ms":int(c.end_ms),"text":c.source_text}
        for c in record.segments]
    translated=()
    if state.artifact is not None:
        translated=state.artifact.translations
        if len(translated)!=len(ja):
            raise ValueError("Cached Gemini translation and transcript do not match")
    a=[{"start_ms":item["start_ms"],"end_ms":item["end_ms"],"text":txt}
       for item,txt in zip(ja,translated) if isinstance(txt,str) and txt.strip()]
    stage_usage=(getattr(state.artifact,'provenance',{}).get('usage') if state.artifact else None)
    return {"status":state.status,"source_video_id":video_id,
            "transcript_hash":record.content_hash,"ja":ja,"a":a,
            "a_cached":len(a)==len(ja),"transcript_provider":record.provider,
            "translation_model":state.artifact.identity.model if state.artifact else None,
            "a_stage_usage":stage_usage if isinstance(stage_usage,dict) else None}


def acquire_existing_public_transcript(video_url: str, *, service=None):
    """UI must call this only from a deliberate button click; no paid translation."""
    video_id=video_url if isinstance(video_url,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',video_url) else youtube_video_id(video_url)
    if not video_id or len(video_id)!=11:
        raise ValueError("Invalid YouTube URL")
    service=service or ArchiveTranslationService()
    service.acquire_public_transcript(f"https://www.youtube.com/watch?v={video_id}")
    return inspect_existing(video_url,service=service)
