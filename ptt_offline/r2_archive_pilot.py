"""Build and audit a replaceable local R2 archive pilot from staged sources."""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from .ptt_aid_identity import verify_aid_url
from .public_today_contract import ContractError
from .r2_archive_export import _write_deterministic_gzip, write_archive_rows
from .url_epoch_authority import reconstruct_events

TPE=ZoneInfo("Asia/Taipei")
TITLE_DAY=re.compile(r"\(115(\d{2})(\d{2})\)")
REQUIRED_STAGING={"aid","source_line","source_page","kind","author","content",
                  "ptt_date","ptt_time","occurred_at","source_url","source_path",
                  "source_record_key","coverage_day","coverage_status","finalized",
                  "time_quality"}


def _connect(path: Path) -> sqlite3.Connection:
    db=sqlite3.connect(f"file:{path}?mode=ro&immutable=1",uri=True)
    db.row_factory=sqlite3.Row
    return db


def _title_day(title: str) -> str:
    match=TITLE_DAY.search(title or "")
    if not match:
        raise ContractError("article title lacks ROC day identity")
    return f"2026-{match.group(1)}-{match.group(2)}"


def _load_source(path: Path, *, provenance: str, title_day_min: str | None,
                 title_day_max: str | None) -> tuple[list[dict],list[dict]]:
    staged=[]
    articles=[]
    with _connect(path) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ContractError("source quick_check failed")
        for article in db.execute("SELECT * FROM articles WHERE board='C_Chat' ORDER BY id"):
            try:
                thread_day=_title_day(article["title_hint"])
            except ContractError:
                continue
            if title_day_min and thread_day < title_day_min:
                continue
            if title_day_max and thread_day > title_day_max:
                continue
            raw=[dict(row) for row in db.execute(
                "SELECT source_line,source_page,kind,author,content,ptt_date,ptt_time,collected_at "
                "FROM pushes WHERE article_id=? ORDER BY source_line",(article["id"],)
            )]
            events=reconstruct_events(
                board=article["board"],aid=article["aid"],url=article["url"],
                pushes=raw,identity_verifier=verify_aid_url,
                reviewed_chronology_exceptions=True,
            )
            exception_lines=[e["source_line"] for e in events if e["time_quality"] == "source-minute-regression"]
            articles.append({"aid":article["aid"],"thread_day":thread_day,
                             "source_path":provenance,"pushes":len(events),
                             "chronology_exception_lines":exception_lines})
            for event in events:
                staged.append({
                    "aid":event["aid"],"source_line":event["source_line"],
                    "source_page":event.get("source_page"),"kind":event.get("kind"),
                    "author":event.get("author") or "","content":event.get("content") or "",
                    "ptt_date":event["ptt_date"],"ptt_time":event["ptt_time"],
                    "occurred_at":event["occurred_at"],"source_url":article["url"],
                    "source_path":provenance,"source_record_key":event["source_record_key"],
                    "time_quality":event["time_quality"],
                    **({"chronology_note":event["chronology_note"]} if "chronology_note" in event else {}),
                })
    return staged,articles


def _audit(out_dir: Path, manifest: dict, staging_rows: list[dict],
           articles: list[dict]) -> dict:
    errors=[]
    seen=set()
    duplicates=[]
    invalid_timestamps=0
    chunk_pushes=0
    first=None
    last=None
    priority={"COMPLETE":0,"UNKNOWN":1,"PARTIAL":2}
    for item in manifest["objects"]:
        target=out_dir/item["key"]
        if not target.is_file():
            errors.append(f"missing object {item['key']}")
            continue
        try:
            with gzip.open(target,"rt",encoding="utf-8") as handle:
                payload=json.load(handle)
        except Exception as exc:
            errors.append(f"gzip/json readback {item['key']}: {exc}")
            continue
        raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        if sha256(raw).hexdigest() != item["sha256"]:
            errors.append(f"sha mismatch {item['key']}")
        if len(payload["pushes"]) != item["pushes"]:
            errors.append(f"push count mismatch {item['key']}")
        if payload["coverage_status"] != item["coverage_status"] or payload["finalized"] != item["finalized"]:
            errors.append(f"coverage metadata mismatch {item['key']}")
        start=datetime.fromisoformat(payload["bucket_start"].replace("Z","+00:00"))
        end=datetime.fromisoformat(payload["bucket_end"].replace("Z","+00:00"))
        prior=None
        row_statuses=[]
        for row in payload["pushes"]:
            row_statuses.append(row["coverage_status"])
            if not REQUIRED_STAGING <= set(row):
                errors.append(f"staging fields missing {row.get('source_record_key')}")
            try:
                occurred=datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00"))
            except Exception:
                invalid_timestamps+=1
                continue
            if occurred.second != 0 or occurred.microsecond != 0:
                invalid_timestamps+=1
            if not start <= occurred < end:
                errors.append(f"wrong chunk {row['source_record_key']}")
            if row["coverage_day"] != occurred.astimezone(TPE).date().isoformat():
                errors.append(f"wrong coverage day {row['source_record_key']}")
            if prior and occurred < prior:
                errors.append(f"chunk order regression {item['key']}")
            prior=occurred
            first=occurred if first is None or occurred < first else first
            last=occurred if last is None or occurred > last else last
            record=row["source_record_key"]
            if record in seen:
                duplicates.append(record)
            seen.add(record)
            expected_finalized=(row["coverage_status"] == "COMPLETE")
            if row["finalized"] != expected_finalized:
                errors.append(f"row finalized mismatch {record}")
            if not row.get("source_path"):
                errors.append(f"missing provenance {record}")
        expected_status=max(row_statuses,key=priority.get)
        if item["coverage_status"] != expected_status:
            errors.append(f"object status is not conservative {item['key']}")
        if item["finalized"] != (item["coverage_status"] == "COMPLETE"):
            errors.append(f"object finalized mismatch {item['key']}")
        chunk_pushes+=len(payload["pushes"])
    if chunk_pushes != manifest["total_pushes"]:
        errors.append("manifest total_pushes != chunk sum")
    if len(manifest["objects"]) != manifest["total_objects"]:
        errors.append("manifest total_objects mismatch")
    if len(staging_rows) != manifest["total_pushes"]:
        errors.append("staging count != manifest total_pushes")
    staging_path=out_dir/"staging/pushes.jsonl.gz"
    try:
        with gzip.open(staging_path,"rt",encoding="utf-8") as handle:
            staged_readback=[json.loads(line) for line in handle if line.strip()]
        if len(staged_readback) != len(staging_rows):
            errors.append("staging gzip readback count mismatch")
        if {row["source_record_key"] for row in staged_readback} != {row["source_record_key"] for row in staging_rows}:
            errors.append("staging gzip readback identity mismatch")
    except Exception as exc:
        errors.append(f"staging gzip/json readback: {exc}")
    chronology=[{"aid":row["aid"],"source_line":row["source_line"],
                 "occurred_at":row["occurred_at"],"note":row.get("chronology_note")}
                for row in staging_rows if row["time_quality"] == "source-minute-regression"]
    daily=Counter(row["coverage_day"] for row in staging_rows)
    return {
        "from_day":manifest["from_day_taipei"],"through_day":manifest["through_day_taipei"],
        "total_pushes":manifest["total_pushes"],"total_objects":manifest["total_objects"],
        "total_gzip_bytes":sum(item["bytes_gzip"] for item in manifest["objects"]),
        "daily_push_counts":dict(sorted(daily.items())),
        "finalized_objects":sum(bool(item["finalized"]) for item in manifest["objects"]),
        "replaceable_objects":sum(not item["finalized"] for item in manifest["objects"]),
        "duplicate_source_record_keys":len(duplicates),"duplicate_keys":duplicates,
        "invalid_timestamps":invalid_timestamps,"chronology_exceptions":chronology,
        "rejected_articles":0,"rejected_rows":0,
        "first_occurred_at":first.isoformat().replace("+00:00","Z") if first else None,
        "last_occurred_at":last.isoformat().replace("+00:00","Z") if last else None,
        "articles":articles,"local_readback_status":"PASS" if not errors else "FAIL",
        "manifest_consistency_status":"PASS" if not errors else "FAIL","errors":errors,
    }


def build(*,backfill: Path, operational: Path, operational_provenance: str,
          coverage_path: Path, out_dir: Path) -> dict:
    coverage=json.loads(coverage_path.read_text(encoding="utf-8"))
    days=coverage["days"]
    day_map={item["day"]:item for item in days}
    from_day=min(day_map)
    through_day=max(day_map)
    start=datetime.combine(date.fromisoformat(from_day),datetime.min.time(),tzinfo=TPE).astimezone(timezone.utc)
    end=datetime.combine(date.fromisoformat(through_day)+timedelta(days=1),datetime.min.time(),tzinfo=TPE).astimezone(timezone.utc)
    backfill_rows,backfill_articles=_load_source(
        backfill,provenance=str(backfill),title_day_min=None,title_day_max="2026-10-07")
    operational_rows,operational_articles=_load_source(
        operational,provenance=operational_provenance,title_day_min="2026-10-08",title_day_max=None)
    rows=[]
    for row in backfill_rows+operational_rows:
        occurred=datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00"))
        if not start <= occurred < end:
            continue
        coverage_day=occurred.astimezone(TPE).date().isoformat()
        item=day_map[coverage_day]
        row.update(coverage_day=coverage_day,coverage_status=item["coverage_status"],finalized=item["finalized"])
        rows.append(row)
    rows.sort(key=lambda r:(r["source_path"],r["aid"],r["source_line"]))
    staging=out_dir/"staging/pushes.jsonl.gz"
    staging_raw=("".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in rows)).encode("utf-8")
    _write_deterministic_gzip(staging,staging_raw)
    manifest=write_archive_rows(
        rows,from_day=from_day,through_day=through_day,out_dir=out_dir,days=days,
        manifest_name="2026-10-pilot.json",
    )
    (out_dir/"coverage.json").write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    audit=_audit(out_dir,manifest,rows,backfill_articles+operational_articles)
    audit["staging_path"]=str(staging)
    audit["staging_gzip_bytes"]=staging.stat().st_size
    (out_dir/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if audit["local_readback_status"] != "PASS":
        raise ContractError("local archive audit failed: "+json.dumps(audit["errors"],ensure_ascii=False))
    return audit


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--backfill",required=True,type=Path)
    parser.add_argument("--operational",required=True,type=Path)
    parser.add_argument("--operational-provenance",required=True)
    parser.add_argument("--coverage",required=True,type=Path)
    parser.add_argument("--out-dir",required=True,type=Path)
    args=parser.parse_args(argv)
    print(json.dumps(build(backfill=args.backfill,operational=args.operational,
                           operational_provenance=args.operational_provenance,
                           coverage_path=args.coverage,out_dir=args.out_dir),
                     ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
