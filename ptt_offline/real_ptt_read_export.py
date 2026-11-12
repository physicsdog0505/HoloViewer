"""Read-only genuine Collector article page for #68 product acceptance.

Records are raw SQLite pushes (not fabricated canonical event timestamps).
This is NOT a D1 Publisher and does not rewrite historical year.
"""
import argparse
import json
from .collector_source_preview import open_source, verify_schema
from .ptt_aid_identity import identity_receipt
from .public_today_contract import normalize_public_aid, ContractError

def read_article(db, *, aid, after_line=0, limit=300):
    if type(after_line) is not int or after_line<0 or type(limit) is not int or not 1<=limit<=300:
        raise ContractError("invalid read-only PTT pagination")
    aid=normalize_public_aid(aid)
    verify_schema(db)
    matches=db.execute("SELECT id,board,aid,url FROM articles WHERE board='C_Chat' AND aid IN (?,?)",
                       (aid,"#"+aid)).fetchall()
    if len(matches)!=1: raise ContractError("exactly one genuine article required")
    article_id,board,real_aid,url=matches[0]
    identity=identity_receipt(board,real_aid,url)
    rows=db.execute("""SELECT source_line,source_page,kind,author,content,ptt_date,ptt_time,collected_at
         FROM pushes WHERE article_id=? AND source_line>?
         ORDER BY source_line LIMIT ?""",(article_id,after_line,limit+1)).fetchall()
    keys=("source_line","source_page","kind","author","content","ptt_date","ptt_time","collected_at")
    visible=[dict(zip(keys,row)) for row in rows[:limit]]
    return {"schema_version":"ptt-collector-raw-v1","origin":"real-collector-sqlite",
      "source_identity":identity,"timestamp_status":"RAW_MONTH_DAY_TIME_NO_VERIFIED_YEAR",
      "aid":aid,"pushes":visible,"has_more":len(rows)>limit,
      "next_after_source_line":visible[-1]["source_line"] if len(rows)>limit else None,
      "canonical_d1_published":False}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",required=True)
    parser.add_argument("--aid",required=True)
    parser.add_argument("--after-line",type=int,default=0)
    parser.add_argument("--limit",type=int,default=300)
    parser.add_argument("--out",required=True)
    args=parser.parse_args(argv)
    with open_source(args.source) as db:
        result=read_article(db,aid=args.aid,after_line=args.after_line,limit=args.limit)
    with open(args.out,"x",encoding="utf-8") as output:
        json.dump(result,output,ensure_ascii=False,indent=2)
        output.write("\n")
    print(json.dumps({"out":args.out,"rows":len(result["pushes"]),
        "has_more":result["has_more"],"source":"REAL_COLLECTOR_READ_ONLY"}))

if __name__=="__main__":main()
