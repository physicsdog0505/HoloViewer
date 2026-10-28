"""Build a month artifact from an explicit, per-AID accepted source set.

This is a read-only source adapter.  It never discovers articles, crawls PTT,
or mutates a source database.  Every source file is SHA-256 pinned and every
article is gated independently before a new consolidated SQLite is created.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION="holoviewer-ptt-accepted-month-v1"
RAW_RULE="collector_raw_final_gap_free_v2"
WEB_RULE="web_declared_parsed_stored_contiguous_floor_v1"


class AcceptedMonthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AcceptedMonthSpec:
    accepted_set_path: Path
    source_root: Path
    web_sqlite_path: Path
    output_sqlite_path: Path
    output_audit_path: Path


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


def _read_only(path: Path) -> sqlite3.Connection:
    connection=sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1",uri=True)
    connection.row_factory=sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _require_sha(value: Any, label: str) -> str:
    text=str(value or "")
    if len(text)!=64 or any(char not in "0123456789abcdef" for char in text):
        raise AcceptedMonthError(f"{label} must be a lowercase SHA-256")
    return text


def _load_accepted_set(path: Path) -> tuple[dict[str,Any],str]:
    raw=path.read_bytes()
    try:
        accepted=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise AcceptedMonthError("accepted set is unreadable") from exc
    if accepted.get("schema_version")!=SCHEMA_VERSION:
        raise AcceptedMonthError("unsupported accepted-set schema")
    month=accepted.get("month")
    if not isinstance(month,str) or len(month)!=7 or month[4]!="-":
        raise AcceptedMonthError("accepted-set month must be YYYY-MM")
    policy=accepted.get("policy",{})
    threshold=policy.get("raw_required_at_or_above")
    if not isinstance(threshold,int) or threshold<1:
        raise AcceptedMonthError("accepted-set threshold is invalid")
    articles=accepted.get("articles")
    if not isinstance(articles,list) or not articles:
        raise AcceptedMonthError("accepted set has no articles")
    expected=accepted.get("expected",{})
    if expected.get("articles")!=len(articles):
        raise AcceptedMonthError("accepted-set article count mismatch")
    aids=[item.get("ptt_aid") for item in articles]
    web_aids=[item.get("web_aid") for item in articles]
    if len(set(aids))!=len(aids) or len(set(web_aids))!=len(web_aids):
        raise AcceptedMonthError("accepted set contains duplicate AIDs")
    high=low=0
    for item in articles:
        gate=item.get("gate_push_count")
        kind=item.get("accepted_source_kind")
        if not isinstance(gate,int) or gate<0:
            raise AcceptedMonthError("accepted-set gate count is invalid")
        if not str(item.get("date","")).startswith(month+"-"):
            raise AcceptedMonthError("accepted-set article is outside month")
        if gate>=threshold:
            high+=1
            if kind!="Raw":
                raise AcceptedMonthError("high-risk AID is not bound to Raw")
        else:
            low+=1
            if kind!="Web":
                raise AcceptedMonthError("low-risk AID is not bound to Web")
        _require_sha(item.get("source_sha256"),"article source")
    if (expected.get("high_risk_raw")!=high or
            expected.get("low_risk_web")!=low or high+low!=len(articles)):
        raise AcceptedMonthError("accepted-set policy counts mismatch")
    return accepted,sha256(raw).hexdigest()


def _verify_source_files(accepted: dict[str,Any], source_root: Path,
                         web_path: Path) -> dict[str,Path]:
    web=accepted.get("web_source",{})
    if web.get("basename")!=web_path.name:
        raise AcceptedMonthError("Web source basename mismatch")
    if _digest(web_path)!=_require_sha(web.get("sha256"),"Web source"):
        raise AcceptedMonthError("Web source SHA-256 mismatch")
    paths={web_path.name:web_path}
    raw_sources=accepted.get("raw_sources")
    if not isinstance(raw_sources,list) or not raw_sources:
        raise AcceptedMonthError("accepted set has no Raw sources")
    for source in raw_sources:
        basename=source.get("basename")
        if (not isinstance(basename,str) or not basename or
                Path(basename).name!=basename or basename in paths):
            raise AcceptedMonthError("Raw source basename is invalid or duplicated")
        path=source_root/basename
        if _digest(path)!=_require_sha(source.get("sha256"),"Raw source"):
            raise AcceptedMonthError(f"Raw source SHA-256 mismatch: {basename}")
        paths[basename]=path
    declared={(item["basename"],item["sha256"]) for item in raw_sources}
    used={(item["source_basename"],item["source_sha256"])
          for item in accepted["articles"] if item["accepted_source_kind"]=="Raw"}
    if used!=declared:
        raise AcceptedMonthError("accepted-set Raw source inventory differs from AID bindings")
    return paths


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _raw_article(db: sqlite3.Connection, item: dict[str,Any]) -> dict[str,Any]:
    required={"articles","pushes","article_source_lines","article_screens"}
    if not required<=_table_names(db):
        raise AcceptedMonthError("Raw source schema is incomplete")
    if db.execute("PRAGMA quick_check").fetchone()[0]!="ok":
        raise AcceptedMonthError("Raw source quick_check failed")
    rows=db.execute("SELECT * FROM articles WHERE aid=?",(item["ptt_aid"],)).fetchall()
    if len(rows)!=1:
        raise AcceptedMonthError(f"Raw AID lookup is not unique: {item['ptt_aid']}")
    article=dict(rows[0]); article_id=article["id"]
    last_page=article.get("last_page"); total_pages=article.get("total_pages")
    last_line=article.get("last_source_line")
    if not (isinstance(last_page,int) and last_page>0 and last_page==total_pages and
            isinstance(last_line,int) and last_line>0):
        raise AcceptedMonthError(f"Raw final-page gate failed: {item['ptt_aid']}")
    lines=[dict(row) for row in db.execute(
        "SELECT * FROM article_source_lines WHERE article_id=? ORDER BY source_line",
        (article_id,))]
    if ([row["source_line"] for row in lines]!=list(range(1,last_line+1)) or
            any(not 1<=row["source_page"]<=last_page for row in lines)):
        raise AcceptedMonthError(f"Raw source-line coverage failed: {item['ptt_aid']}")
    screens=[dict(row) for row in db.execute(
        "SELECT * FROM article_screens WHERE article_id=? ORDER BY source_page,start_line",
        (article_id,))]
    if ({row["source_page"] for row in screens}!=set(range(1,last_page+1)) or
            not screens or screens[0]["start_line"]!=1 or
            max(row["end_line"] for row in screens)<last_line):
        raise AcceptedMonthError(f"Raw screen page/final coverage failed: {item['ptt_aid']}")
    covered=0
    for screen in sorted(screens,key=lambda row:(row["start_line"],row["end_line"])):
        if screen["start_line"]>covered+1 or screen["end_line"]<screen["start_line"]:
            raise AcceptedMonthError(f"Raw screen coverage gap: {item['ptt_aid']}")
        covered=max(covered,screen["end_line"])
    if covered<last_line:
        raise AcceptedMonthError(f"Raw screen final-line gap: {item['ptt_aid']}")
    pushes=[dict(row) for row in db.execute(
        "SELECT * FROM pushes WHERE article_id=? ORDER BY source_line",(article_id,))]
    if len(pushes)!=item.get("expected_stored_push_count"):
        raise AcceptedMonthError(f"Raw push count mismatch: {item['ptt_aid']}")
    line_pages={row["source_line"]:row["source_page"] for row in lines}
    if (len({row["source_line"] for row in pushes})!=len(pushes) or
            any(line_pages.get(row["source_line"])!=row["source_page"] for row in pushes)):
        raise AcceptedMonthError(f"Raw push/source identity failed: {item['ptt_aid']}")
    return {"article":article,"pushes":pushes,"lines":lines,"screens":screens}


def _web_article(db: sqlite3.Connection, item: dict[str,Any]) -> dict[str,Any]:
    if not {"web_articles","web_pushes"}<=_table_names(db):
        raise AcceptedMonthError("Web source schema is incomplete")
    rows=db.execute("SELECT * FROM web_articles WHERE aid=?",(item["web_aid"],)).fetchall()
    if len(rows)!=1:
        raise AcceptedMonthError(f"Web AID lookup is not unique: {item['web_aid']}")
    article=dict(rows[0]); article_id=article["id"]
    pushes=[dict(row) for row in db.execute(
        "SELECT * FROM web_pushes WHERE web_article_id=? ORDER BY floor",(article_id,))]
    floors=[row["floor"] for row in pushes]
    expected=item.get("expected_stored_push_count")
    if not (article["declared_push_count"]==article["parsed_push_count"]==
            expected==len(pushes) and floors==list(range(1,expected+1))):
        raise AcceptedMonthError(f"Web completeness/floor gate failed: {item['ptt_aid']}")
    body=None
    if "web_article_bodies" in _table_names(db):
        row=db.execute("SELECT * FROM web_article_bodies WHERE web_article_id=?",
                       (article_id,)).fetchone()
        body=dict(row) if row else None
    return {"article":article,"pushes":pushes,"body":body}


def _create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    PRAGMA page_size=4096;
    PRAGMA foreign_keys=ON;
    CREATE TABLE artifact_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT NOT NULL,aid TEXT NOT NULL,
      url TEXT NOT NULL,title_hint TEXT NOT NULL,created_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,last_page INTEGER,total_pages INTEGER,
      last_source_line INTEGER,UNIQUE(board,aid));
    CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER NOT NULL REFERENCES articles(id),
      source_line INTEGER NOT NULL,source_page INTEGER NOT NULL,web_floor INTEGER,
      kind TEXT NOT NULL,author TEXT NOT NULL,content TEXT NOT NULL,ptt_date TEXT NOT NULL,
      ptt_time TEXT NOT NULL,collected_at TEXT NOT NULL,UNIQUE(article_id,source_line));
    CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER NOT NULL REFERENCES articles(id),
      source_page INTEGER NOT NULL,total_pages INTEGER NOT NULL,start_line INTEGER NOT NULL,
      end_line INTEGER NOT NULL,captured_at TEXT NOT NULL,UNIQUE(article_id,start_line,end_line));
    CREATE TABLE article_source_lines(id INTEGER PRIMARY KEY,article_id INTEGER NOT NULL REFERENCES articles(id),
      source_line INTEGER NOT NULL,source_page INTEGER NOT NULL,content TEXT NOT NULL,
      captured_at TEXT NOT NULL,UNIQUE(article_id,source_line));
    CREATE TABLE article_bodies(article_id INTEGER PRIMARY KEY REFERENCES articles(id),
      body_text TEXT NOT NULL,captured_at TEXT NOT NULL);
    CREATE TABLE article_provenance(article_id INTEGER PRIMARY KEY REFERENCES articles(id),
      roster_date TEXT NOT NULL,period TEXT NOT NULL,web_aid TEXT NOT NULL,ptt_aid TEXT NOT NULL,
      source_kind TEXT NOT NULL CHECK(source_kind IN ('Raw','Web')),source_path TEXT NOT NULL,
      source_sha256 TEXT NOT NULL,source_article_id INTEGER NOT NULL,
      source_locator_semantics TEXT NOT NULL,declared_push_count INTEGER,
      parsed_push_count INTEGER,stored_push_count INTEGER NOT NULL,
      completeness_status TEXT NOT NULL CHECK(completeness_status='COMPLETE'),
      completeness_rule TEXT NOT NULL,logical_sha256 TEXT NOT NULL,
      UNIQUE(web_aid),UNIQUE(ptt_aid));
    CREATE INDEX pushes_article_order ON pushes(article_id,source_line);
    CREATE INDEX pushes_author ON pushes(author);
    CREATE INDEX article_source_lines_article_order ON article_source_lines(article_id,source_line);
    """)


def _logical_hash(item: dict[str,Any], source: dict[str,Any]) -> str:
    if item["accepted_source_kind"]=="Raw":
        payload={"item":item,"article":source["article"],"pushes":source["pushes"],
                 "lines":source["lines"],"screens":source["screens"]}
    else:
        payload={"item":item,"article":source["article"],"pushes":source["pushes"],
                 "body":source["body"]}
    return _canonical_digest(payload)


def _write_article(db: sqlite3.Connection, article_id: int, item: dict[str,Any],
                   source: dict[str,Any]) -> dict[str,Any]:
    kind=item["accepted_source_kind"]; logical=_logical_hash(item,source)
    if kind=="Raw":
        article=source["article"]
        db.execute("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)",(
            article_id,article["board"],article["aid"],article["url"],
            article["title_hint"],article["created_at"],article["last_seen_at"],
            article["last_page"],article["total_pages"],article["last_source_line"]))
        for push_id,row in enumerate(source["pushes"],start=1):
            db.execute("INSERT INTO pushes VALUES(NULL,?,?,?,?,?,?,?,?,?,?)",(
                article_id,row["source_line"],row["source_page"],None,row["kind"],
                row["author"],row["content"],row["ptt_date"],row["ptt_time"],
                row["collected_at"]))
        for row in source["lines"]:
            db.execute("INSERT INTO article_source_lines VALUES(NULL,?,?,?,?,?)",(
                article_id,row["source_line"],row["source_page"],row["content"],
                row["captured_at"]))
        for row in source["screens"]:
            db.execute("INSERT INTO article_screens VALUES(NULL,?,?,?,?,?,?)",(
                article_id,row["source_page"],row["total_pages"],row["start_line"],
                row["end_line"],row["captured_at"]))
        source_article_id=article["id"]; declared=parsed=None
        locator="collector_source_line"; rule=RAW_RULE
    else:
        article=source["article"]
        db.execute("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)",(
            article_id,article["board"],item["ptt_aid"],article["source_url"],
            article["title"],article["fetched_at"],article["fetched_at"],None,None,
            len(source["pushes"])))
        for row in source["pushes"]:
            db.execute("INSERT INTO pushes VALUES(NULL,?,?,?,?,?,?,?,?,?,?)",(
                article_id,row["floor"],0,row["floor"],row["kind"],row["author"],
                row["content"],row["ptt_date"],row["ptt_time"],row["fetched_at"]))
        if source["body"]:
            db.execute("INSERT INTO article_bodies VALUES(?,?,?)",(
                article_id,source["body"]["body_text"],source["body"]["fetched_at"]))
        source_article_id=article["id"]
        declared=article["declared_push_count"]; parsed=article["parsed_push_count"]
        locator="web_floor"; rule=WEB_RULE
    stored=len(source["pushes"])
    db.execute("INSERT INTO article_provenance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
        article_id,item["date"],item["period"],item["web_aid"],item["ptt_aid"],kind,
        item["source_basename"],item["source_sha256"],source_article_id,locator,
        declared,parsed,stored,"COMPLETE",rule,logical))
    return {"date":item["date"],"period":item["period"],"web_aid":item["web_aid"],
            "ptt_aid":item["ptt_aid"],"source_kind":kind,
            "source_path":item["source_basename"],"pushes":stored,
            "gate_push_count":item["gate_push_count"],"completeness_rule":rule,
            "logical_sha256":logical}


def _table_counts(db: sqlite3.Connection) -> dict[str,int]:
    names=("artifact_metadata","articles","pushes","article_screens",
           "article_source_lines","article_bodies","article_provenance")
    return {name:db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in names}


def build_accepted_month(spec: AcceptedMonthSpec) -> dict[str,Any]:
    """Validate every accepted AID and create a fresh consolidated artifact."""
    if spec.output_sqlite_path.exists() or spec.output_audit_path.exists():
        raise AcceptedMonthError("output already exists")
    accepted,accepted_sha=_load_accepted_set(spec.accepted_set_path)
    paths=_verify_source_files(accepted,spec.source_root,spec.web_sqlite_path)
    input_hashes={name:_digest(path) for name,path in paths.items()}
    raw_dbs={name:_read_only(path) for name,path in paths.items()
             if name!=spec.web_sqlite_path.name}
    web_db=_read_only(spec.web_sqlite_path)
    article_receipts=[]
    spec.output_sqlite_path.parent.mkdir(parents=True,exist_ok=True)
    output=sqlite3.connect(spec.output_sqlite_path)
    try:
        _create_schema(output)
        metadata={"schema_version":SCHEMA_VERSION,"month":accepted["month"],
                  "accepted_set_sha256":accepted_sha,
                  "ledger_commit":accepted["evidence"]["ledger_commit"],
                  "policy":json.dumps(accepted["policy"],sort_keys=True,separators=(",",":"))}
        output.executemany("INSERT INTO artifact_metadata VALUES(?,?)",sorted(metadata.items()))
        for index,item in enumerate(accepted["articles"],start=1):
            if item["accepted_source_kind"]=="Raw":
                source=_raw_article(raw_dbs[item["source_basename"]],item)
            else:
                source=_web_article(web_db,item)
            article_receipts.append(_write_article(output,index,item,source))
        output.commit()
        if output.execute("PRAGMA foreign_key_check").fetchall():
            raise AcceptedMonthError("output foreign_key_check failed")
        if output.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise AcceptedMonthError("output quick_check failed")
        counts=_table_counts(output)
        output.execute("VACUUM")
    except Exception:
        output.close()
        spec.output_sqlite_path.unlink(missing_ok=True)
        raise
    finally:
        for db in raw_dbs.values():
            db.close()
        web_db.close()
    output.close()
    if {name:_digest(path) for name,path in paths.items()}!=input_hashes:
        spec.output_sqlite_path.unlink(missing_ok=True)
        raise AcceptedMonthError("source changed during build")
    sqlite_sha=_digest(spec.output_sqlite_path)
    kind_counts=dict(Counter(item["source_kind"] for item in article_receipts))
    kind_pushes=Counter()
    for item in article_receipts:
        kind_pushes[item["source_kind"]]+=item["pushes"]
    audit={"schema_version":2,
           "dataset":f"issue403-month-{accepted['month'].replace('-','')}-complete",
           "status":"PASS","output_sha256":sqlite_sha,"quick_check":"ok",
           "foreign_key_errors":0,"duplicate_aids":0,
           "articles_complete":len(article_receipts),"web_failures":0,
           "table_counts":counts,"source_kind_counts":kind_counts,
           "source_kind_push_counts":dict(kind_pushes),"articles":article_receipts,
           "accepted_set":{"sha256":accepted_sha,"schema_version":SCHEMA_VERSION,
               "article_count":len(article_receipts),
               "high_risk_raw":accepted["expected"]["high_risk_raw"],
               "low_risk_web":accepted["expected"]["low_risk_web"],
               "missing_aids":[],"extra_aids":[]},
           "source_files":[{"basename":name,"sha256":digest}
                           for name,digest in sorted(input_hashes.items())],
           "evidence":accepted["evidence"]}
    spec.output_audit_path.parent.mkdir(parents=True,exist_ok=True)
    spec.output_audit_path.write_bytes(_canonical(audit))
    return {"status":"PASS","month":accepted["month"],
            "sqlite_path":str(spec.output_sqlite_path),"sqlite_sha256":sqlite_sha,
            "audit_path":str(spec.output_audit_path),
            "audit_sha256":_digest(spec.output_audit_path),
            "accepted_set_sha256":accepted_sha,"articles":len(article_receipts),
            "pushes":counts["pushes"],"high_risk_raw":kind_counts.get("Raw",0),
            "low_risk_web":kind_counts.get("Web",0),"missing_aids":[],"extra_aids":[]}


def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser()
    parser.add_argument("--accepted-set",required=True,type=Path)
    parser.add_argument("--source-root",required=True,type=Path)
    parser.add_argument("--web-sqlite",required=True,type=Path)
    parser.add_argument("--out-sqlite",required=True,type=Path)
    parser.add_argument("--out-audit",required=True,type=Path)
    return parser


def main(argv: Iterable[str]|None=None) -> int:
    args=_parser().parse_args(argv)
    result=build_accepted_month(AcceptedMonthSpec(
        accepted_set_path=args.accepted_set,source_root=args.source_root,
        web_sqlite_path=args.web_sqlite,output_sqlite_path=args.out_sqlite,
        output_audit_path=args.out_audit))
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
