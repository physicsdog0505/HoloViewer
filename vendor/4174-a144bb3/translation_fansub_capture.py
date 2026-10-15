"""Local-only fan-sub evidence capture; separate from operational databases."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json, os, tempfile
from frontend_time import youtube_video_id

def validate_capture(video_url: str, seconds: float, raw_ocr: str,
                     corrected: str, bbox: tuple[int,int,int,int], *, screenshot_sha256: str | None = None) -> dict:
    video_id = youtube_video_id(video_url)
    if video_id is None:
        raise ValueError("Valid YouTube video URL or ID required")
    if not 0 <= seconds <= 86400 or seconds != seconds:
        raise ValueError("Invalid clip time")
    if len(bbox) != 4 or min(bbox) < 0 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError("Invalid OCR region")
    if not corrected.strip():
        raise ValueError("Confirm or correct the reference subtitle before saving")
    if len(raw_ocr) > 10000 or len(corrected) > 10000:
        raise ValueError("Caption length limit exceeded")
    if screenshot_sha256 is not None and (len(screenshot_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in screenshot_sha256)):
        raise ValueError("Invalid screenshot digest")
    return {
        "screenshot_sha256":screenshot_sha256,
        "schema_version":1, "video_id":video_id,
        "reference_url":f"https://www.youtube.com/watch?v={video_id}",
        "clip_time_ms":round(seconds*1000), "roi":list(bbox),
        "raw_ocr":raw_ocr, "corrected_text":corrected.strip(),
        "review_status":"human_corrected",
        "source_japanese_status":"not_yet_linked",
        "translation_a_status":"not_yet_linked",
        "translation_b_status":"not_yet_linked",
    }

def private_capture_root() -> Path:
    """Fixed per-user, non-served storage; reject symlinked directory components."""
    home = Path.home().resolve()
    root = home / ".holoviewer" / "translation-quality-lab" / "captures"
    for part in (home / ".holoviewer", home / ".holoviewer" / "translation-quality-lab", root):
        if part.is_symlink():
            raise ValueError("Private OCR capture path may not contain symlinks")
    return root


def save_capture(root: Path, sample: dict) -> tuple[Path,bool]:
    """Never replace evidence. Data must live outside any static directory."""
    expected = private_capture_root()
    if Path(root).absolute() != expected:
        raise ValueError("OCR evidence must stay in the fixed private capture directory")
    root = expected
    root.mkdir(parents=True,exist_ok=True)
    if root.resolve() != root:
        raise ValueError("Private OCR capture directory redirected")
    raw=json.dumps(sample,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    fingerprint=sha256(raw.encode("utf-8")).hexdigest()[:24]
    path=root/(fingerprint+".json")
    record={"id":fingerprint,"captured_at":datetime.now(timezone.utc).isoformat(),
            "sample":sample}
    tmp=None
    try:
        with tempfile.NamedTemporaryFile("w",dir=root,delete=False,prefix=".ocr-",encoding="utf-8") as stream:
            tmp=Path(stream.name);os.chmod(tmp,0o600)
            json.dump(record,stream,ensure_ascii=False,sort_keys=True,indent=2)
            stream.flush();os.fsync(stream.fileno())
        try:
            os.link(tmp,path)
            return path, True
        except FileExistsError:
            return path, False
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
