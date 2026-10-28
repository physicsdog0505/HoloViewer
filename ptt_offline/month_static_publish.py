"""Fail-closed consolidated-month adapter for Workers Static Assets.

The source SQLite and accepted audit are opened read-only after exact SHA-256
verification.  This module can build an immutable Static Assets package,
publish it to an owner-local filesystem registry, and independently read it
back over HTTP.  It has no Cloudflare, R2, D1, PTT, subprocess, or production
deployment implementation.
"""
from __future__ import annotations

import argparse
import calendar
import json
import shutil
import sqlite3
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .archive_job_evidence import build_archive_job_evidence, build_readback_receipt
from .public_today_contract import ContractError, normalize_public_aid


TPE=ZoneInfo("Asia/Taipei")
ARCHIVE_SCHEMA="ptt-r2-archive-v1"
REGISTRATION_SCHEMA="holoviewer-ptt-month-registration-v1"
PROVENANCE_SCHEMA="holoviewer-ptt-month-provenance-v1"
MAX_HTTP_BYTES=32*1024*1024


@dataclass(frozen=True)
class MonthSource:
    month: str
    sqlite_path: Path
    sqlite_sha256: str
    audit_path: Path
    audit_sha256: str
    article_count: int


class MonthPublishError(ContractError):
    pass


def _digest(path: Path) -> str:
    value=sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""):
            value.update(block)
    return value.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(",",":")).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: Any, *, canonical: bool=False) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(_canonical(value) if canonical else
         (json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode())
    path.write_bytes(raw)


def _read_only(path: Path) -> sqlite3.Connection:
    db=sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1",uri=True)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _month_days(month: str) -> list[str]:
    try:
        year,number=map(int,month.split("-"))
        total=calendar.monthrange(year,number)[1]
    except (ValueError,TypeError) as exc:
        raise MonthPublishError("month must be YYYY-MM") from exc
    if f"{year:04d}-{number:02d}"!=month:
        raise MonthPublishError("month must be canonical YYYY-MM")
    return [f"{month}-{day:02d}" for day in range(1,total+1)]


def _validate_source(spec: MonthSource) -> tuple[dict[str,Any],list[dict[str,Any]]]:
    if _digest(spec.sqlite_path)!=spec.sqlite_sha256:
        raise MonthPublishError("source SQLite SHA-256 mismatch")
    if _digest(spec.audit_path)!=spec.audit_sha256:
        raise MonthPublishError("source audit SHA-256 mismatch")
    try:
        audit=json.loads(spec.audit_path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthPublishError("source audit is unreadable") from exc
    expected_dataset=f"issue403-month-{spec.month.replace('-','')}-complete"
    checks=(
        audit.get("status")=="PASS",
        audit.get("dataset")==expected_dataset,
        audit.get("quick_check")=="ok",
        audit.get("foreign_key_errors")==0,
        audit.get("duplicate_aids")==0,
        audit.get("articles_complete")==spec.article_count,
        audit.get("web_failures")==0,
        audit.get("output_sha256")==spec.sqlite_sha256,
        isinstance(audit.get("table_counts"),dict),
        audit.get("table_counts",{}).get("articles")==spec.article_count,
        audit.get("table_counts",{}).get("article_provenance")==spec.article_count,
        isinstance(audit.get("articles"),list),
        len(audit.get("articles",[]))==spec.article_count,
    )
    if not all(checks):
        raise MonthPublishError("source audit is not exact COMPLETE month evidence")

    with _read_only(spec.sqlite_path) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise MonthPublishError("source SQLite quick_check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise MonthPublishError("source SQLite foreign_key_check failed")
        required={"articles","pushes","article_provenance"}
        tables={row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not required<=tables:
            raise MonthPublishError("source SQLite month schema missing")
        articles=[dict(row) for row in db.execute(
            """SELECT a.*,p.roster_date,p.period,p.web_aid,p.ptt_aid,
                      p.source_kind,p.source_path,p.source_sha256,
                      p.source_locator_semantics,p.declared_push_count,
                      p.parsed_push_count,p.stored_push_count,
                      p.completeness_status,p.completeness_rule,p.logical_sha256
               FROM articles a JOIN article_provenance p ON p.article_id=a.id
               ORDER BY p.roster_date,p.ptt_aid""")]
        if len(articles)!=spec.article_count:
            raise MonthPublishError("source article count mismatch")
        aids=[normalize_public_aid(item["ptt_aid"]) for item in articles]
        if len(aids)!=len(set(aids)):
            raise MonthPublishError("duplicate AID in source month")
        if any(item["completeness_status"]!="COMPLETE" for item in articles):
            raise MonthPublishError("UNKNOWN/PARTIAL article cannot be registered")
        if any(not str(item["roster_date"]).startswith(spec.month+"-") for item in articles):
            raise MonthPublishError("article roster day is outside month")
        db_article_scope=sorted((
            item["roster_date"],item["period"],item["web_aid"],
            normalize_public_aid(item["ptt_aid"]),item["source_kind"],
            item["source_path"],item["stored_push_count"],
            item["completeness_rule"],item["logical_sha256"])
            for item in articles)
        try:
            audit_article_scope=sorted((
                item["date"],item["period"],item["web_aid"],
                normalize_public_aid(item["ptt_aid"]),item["source_kind"],
                item["source_path"],item["pushes"],item["completeness_rule"],
                item["logical_sha256"])
                for item in audit["articles"])
        except (KeyError,TypeError) as exc:
            raise MonthPublishError("accepted audit article scope is invalid") from exc
        if db_article_scope!=audit_article_scope:
            raise MonthPublishError("SQLite article set differs from accepted audit")
        source_kind_counts=dict(Counter(item["source_kind"] for item in articles))
        source_kind_push_counts=Counter()
        for item in articles:
            source_kind_push_counts[item["source_kind"]]+=item["stored_push_count"]
        if (audit.get("source_kind_counts")!=source_kind_counts or
                audit.get("source_kind_push_counts")!=dict(source_kind_push_counts)):
            raise MonthPublishError("source-kind counts differ from accepted audit")
        push_total=db.execute("SELECT count(*) FROM pushes").fetchone()[0]
        if push_total!=audit["table_counts"].get("pushes"):
            raise MonthPublishError("source push count differs from accepted audit")
        for item in articles:
            actual=db.execute("SELECT count(*) FROM pushes WHERE article_id=?",
                              (item["id"],)).fetchone()[0]
            if actual!=item["stored_push_count"]:
                raise MonthPublishError("article stored push count mismatch")
            if item["source_kind"]=="Web":
                row=db.execute(
                    """SELECT count(*),min(web_floor),max(web_floor),
                              count(DISTINCT web_floor),sum(web_floor IS NULL)
                       FROM pushes WHERE article_id=?""",(item["id"],)).fetchone()
                if not (item["declared_push_count"]==item["parsed_push_count"]==
                        item["stored_push_count"]==row[0]==row[3]==row[2]
                        and row[1]==1 and row[4]==0):
                    raise MonthPublishError("Web completeness/floor evidence failed")
            elif item["source_kind"]!="Raw":
                raise MonthPublishError("unsupported source kind")
    if _digest(spec.sqlite_path)!=spec.sqlite_sha256 or _digest(spec.audit_path)!=spec.audit_sha256:
        raise MonthPublishError("source changed during validation")
    return audit,articles


def _events_for_article(db: sqlite3.Connection, article: dict[str,Any],
                        month: str) -> list[dict[str,Any]]:
    raw=[dict(row) for row in db.execute(
        """SELECT source_line,source_page,web_floor,kind,author,content,
                  ptt_date,ptt_time FROM pushes
           WHERE article_id=? ORDER BY source_line""",(article["id"],))]
    try:
        epoch=int(str(article["web_aid"]).split(".")[1])
    except (IndexError,ValueError) as exc:
        raise MonthPublishError("article web identity lacks URL epoch") from exc
    previous=datetime.fromtimestamp(epoch,tz=timezone.utc).astimezone(TPE).replace(
        second=0,microsecond=0)
    aid=normalize_public_aid(article["ptt_aid"])
    output=[]
    for index,source in enumerate(raw,start=1):
        try:
            md=str(source["ptt_date"]).split("/")
            hm=str(source["ptt_time"]).split(":")
            event=datetime(previous.year,int(md[0]),int(md[1]),int(hm[0]),int(hm[1]),
                           tzinfo=TPE)
        except (ValueError,IndexError) as exc:
            raise MonthPublishError(f"invalid PTT timestamp: {aid}:{index}") from exc
        quality="source-minute"
        if event<previous:
            if previous.month==12 and event.month==1:
                event=event.replace(year=previous.year+1)
            else:
                quality="source-minute-regression"
        if event-previous>timedelta(days=45):
            raise MonthPublishError(f"unobserved chronology interval: {aid}:{index}")
        floor=(source["web_floor"] if article["source_kind"]=="Web" else index)
        if floor!=index:
            raise MonthPublishError(f"non-contiguous article floor: {aid}:{floor}")
        collector_line=(source["source_line"] if article["source_kind"]=="Raw" else None)
        locator=(collector_line if collector_line is not None else floor)
        occurred=event.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00","Z")
        row={
            "occurred_at":occurred,
            "minute_epoch":int(event.astimezone(timezone.utc).timestamp()//60),
            "aid":aid,"source_line":collector_line,
            "source_page":source["source_page"] if collector_line is not None else None,
            "source_locator_kind":("collector_source_line" if collector_line is not None
                                   else "web_floor"),
            "source_locator_value":locator,
            "kind":source["kind"],"author":source["author"],"content":source["content"],
            "source_url":article["url"],
            "source_record_key":(f"{aid}:{collector_line}" if collector_line is not None
                                 else f"{aid}:web-floor:{floor}"),
            "floor":floor,
            "floor_quality":("per-thread-ordinal" if collector_line is not None
                             else "verified-web-floor"),
            "source_kind":article["source_kind"],
            # Public package keeps source identity without leaking a local absolute path.
            "source_path":Path(str(article["source_path"])).name,
            "source_sha256":article["source_sha256"],
            "article_logical_sha256":article["logical_sha256"],
            "article_roster_date":article["roster_date"],
            "article_period":article["period"],
            "web_aid":article["web_aid"],
            "month":month,"time_quality":quality,
        }
        row["content_hash"]=_canonical_digest([
            aid,floor,row["kind"],row["author"],row["content"],
            source["ptt_date"],source["ptt_time"],row["source_kind"],
            row["source_locator_kind"],locator,
        ])
        output.append(row)
        previous=event
    return output


def _chunk_key(value: str, month: str) -> str:
    when=datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)
    # Consolidated months can overlap at a day/night-thread boundary. Keep the
    # accepted Archive v1 hourly object shape, but bind objects to the immutable
    # source-month registration so two complete months never overwrite a shared
    # UTC hour.
    return f"ptt/v1/months/{month}/"+when.strftime("chunks/%Y/%m/%d/%H00.json")


def build_month_package(spec: MonthSource, out_dir: Path) -> dict[str,Any]:
    """Build one deterministic immutable month package; never publish it."""
    if out_dir.exists():
        raise MonthPublishError("package output already exists")
    audit,articles=_validate_source(spec)
    public=out_dir/"public"
    rows=[]
    with _read_only(spec.sqlite_path) as db:
        for article in articles:
            rows.extend(_events_for_article(db,article,spec.month))
    month_days=set(_month_days(spec.month))
    for row in rows:
        day=datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00")).astimezone(
            TPE).date().isoformat()
        row["coverage_day"]=day
        row["coverage_status"]="COMPLETE" if day in month_days else "PARTIAL"
        row["finalized"]=day in month_days

    article_scope=[{
        "aid":normalize_public_aid(item["ptt_aid"]),
        "web_aid":item["web_aid"],"roster_date":item["roster_date"],
        "period":item["period"],"source_kind":item["source_kind"],
        "source_path":Path(str(item["source_path"])).name,
        "source_sha256":item["source_sha256"],
        "logical_sha256":item["logical_sha256"],
        "completeness_rule":item["completeness_rule"],
        "stored_push_count":item["stored_push_count"],
    } for item in articles]
    article_set_digest=_canonical_digest(article_scope)
    provenance={"schema_version":PROVENANCE_SCHEMA,"month":spec.month,
                "article_count":len(article_scope),"articles":article_scope}
    provenance_key=f"ptt/v1/provenance/{spec.month}.json"
    provenance_raw=_canonical(provenance)
    provenance_digest=sha256(provenance_raw).hexdigest()
    (public/provenance_key).parent.mkdir(parents=True,exist_ok=True)
    (public/provenance_key).write_bytes(provenance_raw)

    partitions=defaultdict(list)
    identities=[]
    floors=[]
    for row in rows:
        partitions[row["coverage_day"]].append(row)
        identities.append(row["source_record_key"])
        floors.append((row["aid"],row["floor"]))
    if len(identities)!=len(set(identities)) or len(floors)!=len(set(floors)):
        raise MonthPublishError("duplicate canonical row identity")
    objects=[]
    for day in sorted(partitions):
        key=f"ptt/v1/months/{spec.month}/days/{day}/day.json"
        values=sorted(partitions[day],key=lambda row:(
            row["minute_epoch"],row["aid"],row["floor"],row["source_record_key"]))
        start=datetime.fromisoformat(day).replace(tzinfo=TPE).astimezone(timezone.utc)
        status="PARTIAL" if any(row["coverage_status"]!="COMPLETE" for row in values) else "COMPLETE"
        partition_start=start.isoformat(timespec="seconds").replace("+00:00","Z")
        partition_end=(start+timedelta(days=1)).isoformat(
            timespec="seconds").replace("+00:00","Z")
        body={"schema_version":ARCHIVE_SCHEMA,"precision":"minute",
              "partition_start":partition_start,
              "partition_end":partition_end,
              "coverage_status":status,"finalized":status=="COMPLETE","pushes":values}
        raw_bytes=_canonical(body)
        target=public/key
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw_bytes)
        objects.append({"key":key,"sha256":sha256(raw_bytes).hexdigest(),
                        "bytes":len(raw_bytes),"push_count":len(values),
                        "partition_start":partition_start,
                        "partition_end":partition_end,
                        "coverage_status":status,"finalized":status=="COMPLETE"})

    occurred_days=sorted({row["coverage_day"] for row in rows})
    all_days=sorted(month_days|set(occurred_days))
    days=[{"day":day,"coverage_status":"COMPLETE" if day in month_days else "PARTIAL",
           "finalized":day in month_days,
           "reason":("exact-SHA accepted consolidated month; all roster articles COMPLETE"
                     if day in month_days else
                     "overflow pushes retained; outside registered month scope")}
          for day in all_days]
    manifest={
        "schema_version":ARCHIVE_SCHEMA,"delivery_target":"workers-static-assets",
        "precision":"minute","chunk_minutes":1440,"timezone":"UTC","month":spec.month,
        "from_day_taipei":all_days[0],"through_day_taipei":all_days[-1],
        "days":days,"total_pushes":len(rows),"total_objects":len(objects),
        "article_count":len(article_scope),"article_set_sha256":article_set_digest,
        "provenance":{"key":provenance_key,"sha256":provenance_digest},
        "objects":objects,
    }
    manifest_key=f"ptt/v1/manifests/static-assets-full-{spec.month}.json"
    manifest_raw=_canonical(manifest)
    manifest_digest=sha256(manifest_raw).hexdigest()
    (public/manifest_key).parent.mkdir(parents=True,exist_ok=True)
    (public/manifest_key).write_bytes(manifest_raw)
    registration_base={
        "schema_version":REGISTRATION_SCHEMA,"month":spec.month,
        "source":{"sqlite_sha256":spec.sqlite_sha256,"audit_sha256":spec.audit_sha256},
        "source_completeness":{"status":"COMPLETE","article_count":spec.article_count,
                               "duplicate_aids":0,"quick_check":"ok",
                               "foreign_key_errors":0,"web_failures":0},
        "article_set":{"count":len(article_scope),"sha256":article_set_digest},
        "provenance":{"key":provenance_key,"sha256":provenance_digest},
        "manifest":{"key":manifest_key,"digest":manifest_digest,
                    "schema_version":ARCHIVE_SCHEMA},
        "object_count":len(objects),
        "objects":[{"key":item["key"],"sha256":item["sha256"]} for item in objects],
    }
    registration_identity=_canonical_digest(registration_base)
    registration={**registration_base,"registration_identity":registration_identity}
    registration_key=f"ptt/v1/registrations/{spec.month}.json"
    registration_raw=_canonical(registration)
    (public/registration_key).parent.mkdir(parents=True,exist_ok=True)
    (public/registration_key).write_bytes(registration_raw)
    (public/"_headers").write_text(
        "/ptt/v1/chunks/*\n  Content-Type: application/json\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "  Access-Control-Allow-Origin: *\n  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/months/*\n  Content-Type: application/json\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "  Access-Control-Allow-Origin: *\n  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/manifests/*\n  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/registrations/*\n  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/provenance/*\n  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n",encoding="utf-8")
    _write_json(out_dir/"wrangler.jsonc",{
        "name":"holoviewer-ptt-static-assets-history",
        "compatibility_date":"2026-10-18",
        "assets":{"directory":"./public","not_found_handling":"404-page"}})
    receipt={
        "status":"PASS","month":spec.month,"source_completeness":"COMPLETE",
        "build_status":"complete","delivery_status":"not_attempted",
        "readback_verified":False,"source_sqlite_sha256":spec.sqlite_sha256,
        "source_audit_sha256":spec.audit_sha256,"articles":len(article_scope),
        "pushes":len(rows),"source_kind_counts":dict(Counter(
            item["source_kind"] for item in articles)),
        "article_set_sha256":article_set_digest,"manifest_key":manifest_key,
        "manifest_digest":manifest_digest,"registration_key":registration_key,
        "registration_identity":registration_identity,"objects":len(objects),
        "provenance_digest":provenance_digest,
    }
    _write_json(out_dir/"build-receipt.json",receipt)
    if _digest(spec.sqlite_path)!=spec.sqlite_sha256 or _digest(spec.audit_path)!=spec.audit_sha256:
        raise MonthPublishError("source changed during package build")
    return receipt


def _safe_key(value: Any) -> str:
    if not isinstance(value,str) or not value:
        raise MonthPublishError("package object key is invalid")
    key=PurePosixPath(value)
    if key.is_absolute() or ".." in key.parts or str(key)!=value:
        raise MonthPublishError("package object key is unsafe")
    return value


def _package_files(package_dir: Path, receipt: dict[str,Any]) -> list[str]:
    public=package_dir/"public"
    registration_key=_safe_key(receipt.get("registration_key"))
    manifest_key=_safe_key(receipt.get("manifest_key"))
    try:
        registration_raw=(public/registration_key).read_bytes()
        registration=json.loads(registration_raw)
        manifest_raw=(public/manifest_key).read_bytes()
        manifest=json.loads(manifest_raw)
        provenance_key=_safe_key(registration["provenance"]["key"])
        provenance_raw=(public/provenance_key).read_bytes()
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise MonthPublishError("package registration/manifest is unreadable") from exc
    registration_base={key:value for key,value in registration.items()
                       if key!="registration_identity"}
    if (registration_raw!=_canonical(registration) or
            _canonical_digest(registration_base)!=registration.get("registration_identity") or
            registration.get("registration_identity")!=receipt.get("registration_identity")):
        raise MonthPublishError("package registration identity mismatch")
    if (registration["manifest"].get("key")!=manifest_key or
            manifest_raw!=_canonical(manifest) or
            sha256(manifest_raw).hexdigest()!=registration["manifest"]["digest"] or
            registration["manifest"]["digest"]!=receipt.get("manifest_digest")):
        raise MonthPublishError("package manifest digest mismatch")
    if sha256(provenance_raw).hexdigest()!=registration["provenance"]["sha256"]:
        raise MonthPublishError("package provenance digest mismatch")
    object_keys=[]
    for item in registration.get("objects",[]):
        key=_safe_key(item.get("key"))
        try:
            digest=_digest(public/key)
        except OSError as exc:
            raise MonthPublishError(f"package object missing: {key}") from exc
        if digest!=item.get("sha256"):
            raise MonthPublishError(f"package object SHA mismatch: {key}")
        object_keys.append(key)
    manifest_objects=[{"key":item.get("key"),"sha256":item.get("sha256")}
                      for item in manifest.get("objects",[])]
    if (len(object_keys)!=len(set(object_keys)) or
            manifest_objects!=registration.get("objects") or
            len(object_keys)!=registration.get("object_count")):
        raise MonthPublishError("package object set mismatch")
    return object_keys+[provenance_key,manifest_key,registration_key,"_headers"]


def publish_local_immutable(*, package_dir: Path, target_root: Path,
                            simulate_failure: bool=False) -> dict[str,Any]:
    """Copy into an owner-local registry after a complete no-overwrite preflight."""
    receipt=json.loads((package_dir/"build-receipt.json").read_text())
    source_public=package_dir/"public"
    registration_key=receipt["registration_key"]
    target_registration=target_root/registration_key
    if target_registration.exists():
        current=json.loads(target_registration.read_text(encoding="utf-8"))
        if current.get("registration_identity")!=receipt["registration_identity"]:
            raise MonthPublishError("same month has conflicting registration identity")
    files=_package_files(package_dir,receipt)
    planned=[]
    noops=[]
    for key in files:
        source=source_public/key
        target=target_root/key
        if target.exists():
            if _digest(source)!=_digest(target):
                raise MonthPublishError(f"immutable target conflict: {key}")
            noops.append(key)
        else:
            planned.append(key)
    if simulate_failure:
        return {"status":"failed","error_code":"simulated_delivery_failure",
                "uploaded_count":0,"noop_count":len(noops),
                "source_completeness":"COMPLETE","registration_identity":receipt["registration_identity"]}
    # Chunks/provenance first; immutable manifests and registration last.
    last={receipt["manifest_key"],receipt["registration_key"]}
    ordered=[key for key in planned if key not in last]+[
        key for key in (receipt["manifest_key"],receipt["registration_key"]) if key in planned]
    for key in ordered:
        target=target_root/key
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+".issue160.tmp")
        shutil.copyfile(source_public/key,temporary)
        temporary.replace(target)
    return {"status":"succeeded","error_code":None,"uploaded_count":len(planned),
            "noop_count":len(noops),"source_completeness":"COMPLETE",
            "registration_identity":receipt["registration_identity"]}


def _http_bytes(base_url: str, key: str) -> bytes:
    key=_safe_key(key)
    url=base_url.rstrip("/")+"/"+quote(key,safe="/")
    with urlopen(url,timeout=10) as response:
        raw=response.read(MAX_HTTP_BYTES+1)
    if len(raw)>MAX_HTTP_BYTES:
        raise MonthPublishError("readback object exceeds byte limit")
    return raw


def readback_http(*, base_url: str, registration_key: str, job_id: str,
                  observed_at: str, target_identity: str,
                  expected_registration_identity: str) -> dict[str,Any]:
    """Read registration, manifest, provenance and every object over HTTP."""
    target={"kind":"workers-static-assets","identity":target_identity}
    try:
        registration_raw=_http_bytes(base_url,registration_key)
        registration=json.loads(registration_raw)
        manifest_raw=_http_bytes(base_url,registration["manifest"]["key"])
        manifest=json.loads(manifest_raw)
        provenance_raw=_http_bytes(base_url,registration["provenance"]["key"])
        provenance=json.loads(provenance_raw)
        provenance_match=(
            provenance_raw==_canonical(provenance) and
            sha256(provenance_raw).hexdigest()==registration["provenance"]["sha256"])
        verified=0
        unresolved=0
        for item in registration["objects"]:
            try:
                raw=_http_bytes(base_url,item["key"])
                if sha256(raw).hexdigest()==item["sha256"]:
                    verified+=1
                else:
                    unresolved+=1
            except (HTTPError,URLError,OSError):
                unresolved+=1
        manifest_verified=(manifest_raw==_canonical(manifest) and
                           manifest.get("schema_version")==ARCHIVE_SCHEMA)
        manifest_match=(sha256(manifest_raw).hexdigest()==registration["manifest"]["digest"])
        object_count_match=(manifest.get("total_objects")==registration.get("object_count")==
                            len(registration.get("objects",[])))
        object_set_match=(
            [{"key":item.get("key"),"sha256":item.get("sha256")}
             for item in manifest.get("objects",[])]==registration.get("objects"))
        registration_base={key:value for key,value in registration.items()
                           if key!="registration_identity"}
        registration_identity_match=(
            registration_raw==_canonical(registration) and
            _canonical_digest(registration_base)==registration.get("registration_identity") and
            registration.get("registration_identity")==expected_registration_identity)
        article_set_match=(
            _canonical_digest(provenance.get("articles",[]))==
            registration.get("article_set",{}).get("sha256"))
        article_count_match=(
            provenance.get("article_count")==len(provenance.get("articles",[]))==
            registration.get("article_set",{}).get("count")==manifest.get("article_count"))
        scope_match=(manifest.get("month")==registration.get("month") and
                     provenance.get("month")==registration.get("month") and
                     provenance_match and article_count_match and article_set_match and
                     object_set_match and
                     registration_identity_match and
                     manifest.get("article_set_sha256")==registration["article_set"]["sha256"])
        expected=registration["object_count"]
        return build_readback_receipt(
            target=target,job_id=job_id,
            manifest_digest=registration["manifest"]["digest"],
            source_revision=registration["registration_identity"],
            scope={"from_day":manifest["from_day_taipei"],
                   "through_day":manifest["through_day_taipei"],
                   "object_count":expected},objects_expected=expected,
            objects_checked=expected,objects_verified=verified,
            manifest_verified=manifest_verified,manifest_digest_match=manifest_match,
            content_hash_match=(verified==expected and unresolved==0),
            coverage_scope_match=scope_match,object_count_match=object_count_match,
            unresolved_objects=unresolved,pagination_complete=True,
            verification_mode="full_partition",observed_at=observed_at)
    except (KeyError,TypeError,ValueError,json.JSONDecodeError,
            HTTPError,URLError,OSError) as exc:
        if isinstance(exc,MonthPublishError):
            raise
        raise MonthPublishError("readback manifest/registration unavailable") from exc


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*_args: object) -> None:
        return


def run_owner_local(*, spec: MonthSource, package_dir: Path, target_root: Path,
                    observed_at: str,
                    target_identity: str="owner-local-static-assets") -> dict[str,Any]:
    """One-command offline build -> local publish -> HTTP readback pipeline."""
    build=build_month_package(spec,package_dir)
    delivery=publish_local_immutable(package_dir=package_dir,target_root=target_root)
    job_id=f"month-{spec.month}-{build['registration_identity'][:16]}-attempt-1"
    handler=lambda *args,**kwargs:_QuietHandler(*args,directory=str(target_root),**kwargs)
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        readback=readback_http(
            base_url=f"http://127.0.0.1:{server.server_port}",
            registration_key=build["registration_key"],job_id=job_id,
            observed_at=observed_at,target_identity=target_identity,
            expected_registration_identity=build["registration_identity"])
    finally:
        server.shutdown(); thread.join(); server.server_close()
    manifest=json.loads((package_dir/"public"/build["manifest_key"]).read_text())
    source_audit=json.loads(spec.audit_path.read_text(encoding="utf-8"))
    accepted_set=source_audit.get("accepted_set")
    expected_aid={"status":"VERIFIED_COMPLETE","contract_gaps":[]}
    if isinstance(accepted_set,dict):
        expected_aid.update({
            "authority":"per-aid-accepted-set-v1",
            "accepted_set_sha256":accepted_set.get("sha256"),
            "article_count":accepted_set.get("article_count"),
            "high_risk_raw":accepted_set.get("high_risk_raw"),
            "low_risk_web":accepted_set.get("low_risk_web"),
        })
    else:
        expected_aid["authority"]="exact-sha-consolidated-month-audit"
    scope={"from_day":manifest["from_day_taipei"],
           "through_day":manifest["through_day_taipei"],
           "object_count":manifest["total_objects"],
           "thread_scope":[item["aid"] for item in json.loads(
               (package_dir/"public"/manifest["provenance"]["key"]).read_text())["articles"]],
           "thread_scope_authoritative":True}
    evidence=build_archive_job_evidence(
        job_id=job_id,target={"kind":"workers-static-assets","identity":target_identity},
        source_revision=build["registration_identity"],source_hash=spec.sqlite_sha256,
        manifest={"key":build["manifest_key"],"digest":build["manifest_digest"],
                  "schema_version":ARCHIVE_SCHEMA},scope=scope,
        attempted_at=observed_at,succeeded_at=observed_at,attempt_count=1,
        retry_after=observed_at,backoff_seconds=0,error_code=None,
        uploaded_count=delivery["uploaded_count"],
        independently_verified_count=readback["objects_verified"],
        readback_receipt=readback,coverage_days=manifest["days"],job_status="succeeded",
        expected_aid_completeness=expected_aid)
    _write_json(package_dir/"delivery-receipt.json",delivery)
    _write_json(package_dir/"readback-receipt.json",readback)
    _write_json(package_dir/"archive-job-evidence.json",evidence)
    return {"build":build,"delivery":delivery,"readback":readback,"evidence":evidence,
            "production_execution":False,"r2_execution":False}


def _source_from_args(args: argparse.Namespace) -> MonthSource:
    return MonthSource(month=args.month,sqlite_path=args.sqlite,audit_path=args.audit,
                       sqlite_sha256=args.sqlite_sha256,audit_sha256=args.audit_sha256,
                       article_count=args.article_count)


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("build","run-local"):
        item=sub.add_parser(name)
        item.add_argument("--month",required=True)
        item.add_argument("--sqlite",required=True,type=Path)
        item.add_argument("--sqlite-sha256",required=True)
        item.add_argument("--audit",required=True,type=Path)
        item.add_argument("--audit-sha256",required=True)
        item.add_argument("--article-count",required=True,type=int)
        item.add_argument("--out",required=True,type=Path)
        if name=="run-local":
            item.add_argument("--target-root",required=True,type=Path)
            item.add_argument("--observed-at",required=True)
            item.add_argument("--target-identity",default="owner-local-static-assets")
    args=parser.parse_args(argv)
    spec=_source_from_args(args)
    if args.command=="build":
        result=build_month_package(spec,args.out)
    else:
        result=run_owner_local(spec=spec,package_dir=args.out,
                               target_root=args.target_root,observed_at=args.observed_at,
                               target_identity=args.target_identity)
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
