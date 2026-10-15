"""Offline-only Translation Quality Lab evaluation store. No providers, networking or DB writes."""
from __future__ import annotations
import json, math, os, re, tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from translation_fansub_capture import private_capture_root

DIMENSIONS = ("meaning", "natural_zh_tw", "terminology", "context_emotion", "timing", "readability")
TRACKS = ("ja", "a", "b", "c")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

def comparison_root() -> Path:
    parent = private_capture_root().parent
    dest = parent / "comparisons"
    if dest.is_symlink():
        raise ValueError("Unsafe comparison directory")
    return dest

def parse_cues(value, *, limit=500):
    """Accept JSON list [{start_ms,end_ms,text}]. Never infer offsets or alignment."""
    if isinstance(value, str):
        if len(value) > 300000:
            raise ValueError("Input too large")
        value=json.loads(value)
    if not isinstance(value,list) or not 1 <= len(value) <= limit:
        raise ValueError("Expect a nonempty cue list (up to 500)")
    cues=[];previous_end=-1
    for row in value:
        if not isinstance(row,dict):
            raise ValueError("Cue must be an object")
        start,end,txt=row.get("start_ms"),row.get("end_ms"),row.get("text")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or start < previous_end:
            raise ValueError("Invalid or overlapping subtitle times")
        if not isinstance(txt,str) or not txt.strip() or len(txt)>2000:
            raise ValueError("Invalid subtitle text")
        cues.append({"start_ms":start,"end_ms":end,"text":txt.strip()})
        previous_end=end
    return cues

def assemble(*,video_id, start_ms, end_ms, tracks, revisions, notes="", c_offset_ms=0, mapping_confidence="unverified"):
    if not VIDEO_RE.fullmatch(video_id or ""):
        raise ValueError("Invalid YouTube ID")
    if type(start_ms) is not int or type(end_ms) is not int or start_ms<0 or end_ms<=start_ms:
        raise ValueError("Invalid selected time range")
    if not isinstance(tracks,dict) or not all(k in tracks for k in ("ja","a","b")):
        raise ValueError("JA, A and B are mandatory; C is optional")
    if type(c_offset_ms) is not int or abs(c_offset_ms)>86_400_000:
        raise ValueError("Invalid C offset")
    if mapping_confidence not in ("unverified","low","medium","high","manually_verified"):
        raise ValueError("Invalid mapping confidence")
    if not isinstance(notes,str) or len(notes)>4000:
        raise ValueError("Invalid note")
    result={};meta={}
    for kind in TRACKS:
        if kind not in tracks or tracks[kind] in (None,""):
            continue
        parsed=parse_cues(tracks[kind])
        offset=c_offset_ms if kind=="c" else 0
        if not any(row["start_ms"]+offset<end_ms and row["end_ms"]+offset>start_ms for row in parsed):
            raise ValueError(f"No {kind} cues overlap selected period")
        result[kind]=parsed
        info=revisions.get(kind,{})
        if not isinstance(info,dict):
            raise ValueError("Invalid track provenance")
        model=str(info.get("model","manual_import")).strip()
        pipeline=str(info.get("pipeline","offline-import-v1")).strip()
        source=str(info.get("source","manual")).strip()
        if not all((model,pipeline,source)) or max(map(len,(model,pipeline,source)))>200:
            raise ValueError("Invalid provenance")
        meta[kind]={"model":model,"pipeline":pipeline,"source":source}
    return {"schema_version":1,"video_id":video_id,"range_ms":[start_ms,end_ms],
            "tracks":result,"provenance":meta,"c_offset_ms":c_offset_ms,
            "mapping_confidence":mapping_confidence,"notes":notes,
            "api_mode":"offline_import_only","api_requests":0,"input_tokens":None,
            "output_tokens":None,"cost_usd":None}

def visible_rows(comparison):
    """Original JA timeline anchors; independent A/B/C overlap, not fabricated matching."""
    start,end=comparison["range_ms"];tracks=comparison["tracks"]
    result=[]
    for ja in tracks["ja"]:
        if ja["end_ms"]<=start or ja["start_ms"]>=end:
            continue
        row={"start_ms":ja["start_ms"],"end_ms":ja["end_ms"],"ja":ja["text"]}
        for kind in ("a","b","c"):
            offset=comparison["c_offset_ms"] if kind=="c" else 0
            matches=[c["text"] for c in tracks.get(kind,[]) if c["start_ms"]+offset<ja["end_ms"] and c["end_ms"]+offset>ja["start_ms"]]
            row[kind]=" / ".join(matches)
        result.append(row)
    return result

def validate_scores(scores):
    if not isinstance(scores,dict) or any(k not in ("a","b") for k in scores):
        raise ValueError("Only A/B are scored")
    cleaned={}
    for kind in ("a","b"):
        detail=scores.get(kind)
        if not isinstance(detail,dict):
            raise ValueError("Scores for A and B required")
        for d in DIMENSIONS:
            v=detail.get(d)
            if type(v) is not int or not 1<=v<=5:
                raise ValueError("Every dimension needs a 1-5 integer")
        note=detail.get("note","")
        if not isinstance(note,str) or len(note)>4000:
            raise ValueError("Invalid reviewer note")
        cleaned[kind]={**{d:detail[d] for d in DIMENSIONS},"note":note}
    return cleaned

def save_evaluation(comparison,scores):
    """Immutable, local, de-duplicated; does not overwrite previous evaluations."""
    scores=validate_scores(scores)
    root=comparison_root()
    source=json.dumps({"comparison":comparison,"scores":scores},sort_keys=True,ensure_ascii=False)
    digest=sha256(source.encode()).hexdigest()[:24]
    root.mkdir(parents=True,exist_ok=True)
    if root.resolve()!=root or root.is_symlink():
        raise ValueError("Unsafe research directory")
    destination=root/(digest+".json")
    record={"id":digest,"saved_at":datetime.now(timezone.utc).isoformat(),
            "comparison":comparison,"scores":scores}
    temp=None
    try:
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=root,delete=False,prefix=".evaluation-") as file:
            temp=Path(file.name);os.chmod(temp,0o600)
            json.dump(record,file,ensure_ascii=False,indent=2)
            file.flush();os.fsync(file.fileno())
        try:
            os.link(temp,destination)
            return destination,True
        except FileExistsError:
            return destination,False
    finally:
        if temp:temp.unlink(missing_ok=True)

def load_captures(video_id,*,limit=100):
    """Only previously reviewed C OCR captures; source time remains clip local."""
    root=private_capture_root()
    if not root.exists():
        return []
    records=[]
    for path in sorted(root.glob("*.json"))[:limit]:
        if path.is_symlink() or path.stat().st_size>100000:
            continue
        try:
            sample=json.loads(path.read_text(encoding="utf-8"))["sample"]
            if sample.get("video_id")==video_id and sample.get("review_status")=="human_corrected":
                records.append({"start_ms":int(sample["clip_time_ms"]),"text":sample["corrected_text"],"id":path.stem})
        except (ValueError,KeyError,TypeError,OSError):
            continue
    return records

def recent_evaluations(*,limit=20):
    """Read existing private evaluations; no migration, mutation or provider calls."""
    root=comparison_root()
    if not root.exists():
        return []
    records=[]
    for path in sorted(root.glob("*.json"),reverse=True)[:max(1,min(limit,50))]:
        if path.is_symlink() or path.stat().st_size>1_000_000:
            continue
        try:
            record=json.loads(path.read_text(encoding="utf-8"))
            if record.get("comparison",{}).get("api_mode")=="offline_import_only":
                records.append(record)
        except (ValueError,KeyError,OSError,TypeError):
            continue
    return records
