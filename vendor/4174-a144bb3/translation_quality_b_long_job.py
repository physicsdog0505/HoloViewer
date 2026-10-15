"""Offline-first resumable long-video B job with exact Gemini token accounting.

A caller supplies a translator callback. This module never imports Gemini, makes
network requests or overwrites operational databases. Unknown calls stay blocked
after crashes; operators start a NEW versioned job to retry them.
"""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import re
import json, os, tempfile, fcntl
from translation_sentence_reconstruction import SourceCue,reconstruct_sentences
from translation_sentence_reconstruction import require_reviewed_boundaries
from translation_chinese_retiming import retime_sentence,validate_track,ChineseCue
from translation_quality_workspace import parse_cues
from quality_v2_translation_service import QUALITY_V2_DEFAULT_MODEL
from translation_quality_b_semantic_audit import audit_translated_cues
from translation_quality_b_events import append_event

JOB_VERSION="semantic-gemini-long-v1"

def source_cues(value):
    """Validate saved ordered cues, accepting overlapping Corpus speech intervals."""
    if not isinstance(value, (list, tuple)) or not 0 < len(value) <= 10000:
        raise ValueError("Invalid source cue count")
    result = []
    previous_start = -1
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid source cue")
        start, end, label = item.get("start_ms"), item.get("end_ms"), item.get("text")
        if (type(start) is not int or type(end) is not int or start < previous_start
                or end <= start or not isinstance(label, str)
                or not label.strip() or len(label) > 2000):
            raise ValueError("Invalid source cue")
        result.append({"start_ms": start, "end_ms": end, "text": label.strip()})
        previous_start = start
    return result


def nonoverlap_source(cues):
    """Derive B-only sequential time windows; never overwrite original Corpus."""
    result = [dict(cue) for cue in source_cues(cues)]
    for i in range(len(result) - 1):
        left, right = result[i], result[i + 1]
        if left["end_ms"] <= right["start_ms"]:
            continue
        # Preserve order by bisecting the overlap while keeping positive duration.
        boundary = (right["start_ms"] + min(left["end_ms"], right["end_ms"])) // 2
        boundary = max(left["start_ms"] + 1, min(boundary, right["end_ms"] - 1))
        if boundary > left["end_ms"] or boundary < right["start_ms"]:
            raise ValueError("Overlapping source intervals cannot be safely split")
        left["end_ms"] = boundary
        right["start_ms"] = boundary
        if right["end_ms"] <= right["start_ms"]:
            raise ValueError("Overlapping source interval has no remaining duration")
    return result


def job_fingerprint(ja, *, video_id, model=QUALITY_V2_DEFAULT_MODEL, a=None):
    if not isinstance(video_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id) or model!=QUALITY_V2_DEFAULT_MODEL:
        raise ValueError("Invalid video or changed A model")
    return sha256(json.dumps({"ja":source_cues(ja),"video":video_id,
        "model":model,"version":JOB_VERSION,
        "a":source_cues(a) if a else []},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def _atomic_create(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=path.parent,delete=False) as file:
        tmp=Path(file.name)
        os.chmod(tmp,0o600)
        json.dump(payload,file,ensure_ascii=False,sort_keys=True)
        file.flush();os.fsync(file.fileno())
    try:
        os.link(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def read_job(folder, *, fingerprint):
    root=Path(folder)
    if root.is_symlink():raise ValueError("Unsafe job path")
    path=root/(fingerprint+".json")
    if path.is_symlink():raise ValueError("Unsafe checkpoint")
    if not path.exists():return {"fingerprint":fingerprint,"version":JOB_VERSION,"completed":[],"unknown_attempts":[]}
    data=json.loads(path.read_text())
    if data.get("fingerprint")!=fingerprint or data.get("version")!=JOB_VERSION:raise ValueError("Checkpoint identity mismatch")
    return data

def progress(folder, *, fingerprint, total):
    data=read_job(folder,fingerprint=fingerprint)
    pending=Path(folder)/(fingerprint+".pending")
    done=len(data["completed"])
    return {"completed":done,"total":total,"remaining":total-done,
            "blocked":bool(data["unknown_attempts"]) or pending.exists(),
            "requests":len(data["completed"])+len(data["unknown_attempts"])+(1 if pending.exists() else 0),
            "input_tokens":sum(v["input_tokens"] for v in data["completed"]) if all(v["input_tokens"] is not None for v in data["completed"]) else None,
            "output_tokens":sum(v["output_tokens"] for v in data["completed"]) if all(v["output_tokens"] is not None for v in data["completed"]) else None,
            "total_tokens":sum(v.get("total_tokens") for v in data["completed"]) if all(v.get("total_tokens") is not None for v in data["completed"]) else None,
            "reviewed_sentences":sum(v.get("review_flagged") is not None for v in data["completed"]),
            "post_edit_sentences":sum(v.get("review_flagged") is True for v in data["completed"]),
            "cost_usd":None}

def _run_batch_unlocked(ja,a,*,video_id,folder,translate,max_new_requests=5,
              approve_uncertain=False,reviewed_indices=(),max_chars=18,min_duration_ms=900):
    if type(max_new_requests) is not int or not 1<=max_new_requests<=5:raise ValueError("Per-batch request limit 1..5")
    source=nonoverlap_source(ja)
    reconstruction=reconstruct_sentences(tuple(SourceCue(str(i),cue['start_ms'],cue['end_ms'],cue['text']) for i,cue in enumerate(source)))
    approved=reconstruction.uncertain_sentence_indices if approve_uncertain else reviewed_indices
    sentences=require_reviewed_boundaries(reconstruction,approved)
    existing_a=source_cues(a) if a else []
    fingerprint=job_fingerprint(ja,video_id=video_id,a=a)
    root=Path(folder)
    if root.is_symlink():raise ValueError('Unsafe job path')
    root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink():raise ValueError("Unsafe job path")
    # Immutable checkpoint per successful step, with intent file before any request.
    state=read_job(root,fingerprint=fingerprint)
    if state["unknown_attempts"] or (root/(fingerprint+'.pending')).exists():
        raise ValueError("Interrupted request detected; no automatic retry")
    if len(state["completed"])>len(sentences):raise ValueError("Checkpoint has excess segments")
    for i,item in enumerate(state["completed"]):
        if item["index"]!=i or item["source_ids"]!=list(sentences[i].source_ids):
            raise ValueError("Checkpoint source mismatch")
    new=0
    while len(state["completed"])<len(sentences) and new<max_new_requests:
        i=len(state["completed"]);sentence=sentences[i]
        nearby="".join(s.source_text for s in sentences[max(0,i-2):min(len(sentences),i+3)])
        a_refs=" / ".join(c["text"] for c in existing_a
            if c["start_ms"]<sentence.end_ms and c["end_ms"]>sentence.start_ms)
        # This intent file is durable before the network call.
        intent=root/(fingerprint+".pending")
        if intent.exists():raise ValueError("Uncertain pending request; manual inspection required")
        _atomic_create(intent,{"fingerprint":fingerprint,"index":i})
        append_event(root, fingerprint, event="sentence_intent_saved", sentence_index=i)
        try:
            if getattr(translate,"requires_sentence_identity",False):
                translated,usage=translate(sentence.source_text,nearby,a_refs,
                    job_fingerprint=fingerprint,sentence_index=i)
            else:
                translated,usage=translate(sentence.source_text,nearby,a_refs)
            if not isinstance(translated,str) or not translated.strip():raise ValueError("Invalid B result")
            append_event(root, fingerprint, event="sentence_translation_ready", sentence_index=i)
            usage=usage or {}
            def token(name):
                val=usage.get(name)
                return val if type(val) is int and val>=0 else None
            cues=retime_sentence(translated,sentence.start_ms,sentence.end_ms,
                                 max_chars=max_chars,min_duration_ms=min_duration_ms)
            append_event(root, fingerprint, event="retime_complete", sentence_index=i)
            record={"index":i,"source_ids":list(sentence.source_ids),"ja":sentence.source_text,
                "translation":translated,"cues":[asdict(c) for c in cues],
                "input_tokens":token("input_tokens"),"output_tokens":token("output_tokens"),
                "total_tokens":token("total_tokens"),"stage_usage":usage.get("stages"),
                "review_flagged":usage.get("review_flagged"),"review_reason":usage.get("review_reason")}
            next_state={**state,"completed":[*state["completed"],record]}
            # Content-addressed sequential snapshots avoid partial overwrites.
            snapshot=root/(fingerprint+"."+str(i+1)+".json")
            _atomic_create(snapshot,next_state)
            # Update pointer only after snapshot persisted.
            pointer=root/(fingerprint+".json")
            with tempfile.NamedTemporaryFile("w",dir=root,delete=False) as file:
                tmp=Path(file.name);os.chmod(tmp,0o600)
                json.dump(next_state,file,ensure_ascii=False,sort_keys=True)
                file.flush();os.fsync(file.fileno())
            os.replace(tmp,pointer)
            append_event(root, fingerprint, event="checkpoint_saved", sentence_index=i)
            intent.unlink()
            append_event(root, fingerprint, event="pending_cleared", sentence_index=i)
            state=next_state;new+=1
        except BaseException as exc:
            # Never mask the actual failure with a diagnostic I/O error.
            try:
                append_event(root, fingerprint, event="sentence_failed", sentence_index=i, error=exc)
            except Exception:
                pass
            # Intent deliberately remains, protecting against inadvertent API replay.
            raise
    output=[ChineseCue(**cue) for record in state["completed"] for cue in record["cues"]]
    validate_track(tuple(output))
    # Check complete source coverage and no early subtitles before calling a B job finished.
    if len(state["completed"])==len(sentences):
        spans=[record["source_ids"] for record in state["completed"] for _ in record["cues"]]
        audit_translated_cues(source,[asdict(c) for c in output],spans)
    report=progress(root,fingerprint=fingerprint,total=len(sentences))
    report.update({"new_requests":new,"complete":len(state["completed"])==len(sentences),
                   "cues":[asdict(c) for c in output],"fingerprint":fingerprint,
                   "model":QUALITY_V2_DEFAULT_MODEL,"pipeline":JOB_VERSION})
    return report


def verify_complete_b(ja, a, *, video_id, folder):
    """Pure read-only completion audit; never sends or replays a provider call."""
    source = nonoverlap_source(ja)
    reconstruction = reconstruct_sentences(tuple(
        SourceCue(str(i), cue["start_ms"], cue["end_ms"], cue["text"])
        for i, cue in enumerate(source)
    ))
    fingerprint = job_fingerprint(ja, video_id=video_id, a=a)
    root = Path(folder)
    state = read_job(root, fingerprint=fingerprint)
    pending = root / (fingerprint + ".pending")
    if pending.is_symlink() or pending.exists() or state.get("unknown_attempts"):
        raise ValueError("B completion blocked by uncertain request")
    completed = state.get("completed", [])
    if not reconstruction.sentences or len(completed) != len(reconstruction.sentences):
        raise ValueError("B completion is incomplete")
    for index, record in enumerate(completed):
        if record.get("index") != index or record.get("source_ids") != list(reconstruction.sentences[index].source_ids):
            raise ValueError("B completion provenance mismatch")
    cues = tuple(ChineseCue(**cue) for row in completed for cue in row["cues"])
    if not cues:
        raise ValueError("B contains no translated subtitle cues")
    validate_track(cues)
    spans = [row["source_ids"] for row in completed for _ in row["cues"]]
    audit_translated_cues(source, [asdict(cue) for cue in cues], spans)
    return [asdict(cue) for cue in cues]


def run_batch(ja,a,*,video_id,folder,translate,max_new_requests=5,
              approve_uncertain=False,reviewed_indices=(),max_chars=18,min_duration_ms=900):
    """One owner per job across Streamlit reruns / processes; no double API calls."""
    fingerprint=job_fingerprint(ja,video_id=video_id,a=a)
    root=Path(folder)
    if root.is_symlink():raise ValueError("Unsafe job root")
    root.mkdir(parents=True,exist_ok=True)
    lockpath=root/(fingerprint+".lock")
    if lockpath.is_symlink():raise ValueError("Unsafe job lock")
    fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another B translation batch is already running") from exc
        return _run_batch_unlocked(ja,a,video_id=video_id,folder=root,translate=translate,
                                  max_new_requests=max_new_requests,
                                  approve_uncertain=approve_uncertain,reviewed_indices=reviewed_indices,
                                  max_chars=max_chars,min_duration_ms=min_duration_ms)
    finally:
        os.close(fd)
