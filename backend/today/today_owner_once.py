"""Single bounded owner-run Today publisher. Dry-run by default; no automatic retries.
Never print API keys/HMAC secrets or send until explicit CLI source checksum gate.
"""
import argparse, hashlib, hmac, json, os, sys, time
import urllib.request
from .youtube_readonly import approved_roster
API="https://holoviewer-public-api.singlebagel.workers.dev/internal/today/one-shot"
def prepare(read_receipt,roster_document):
    roster,entries=approved_roster(roster_document)
    if read_receipt.get("mode")!="PROVIDER_READ_ONLY" or read_receipt.get("d1_writes")!=0:
        raise ValueError("untrusted provider receipt")
    if read_receipt.get("roster_version")!=roster.version or read_receipt.get("gap") is not False:
        raise ValueError("unverified/gapped roster source")
    if not 1<=len(read_receipt.get("records",[]))<=50 or len(entries)>3:
        raise ValueError("one-shot bounds exceeded")
    allowed={item["id"]:item["group"] for item in entries}
    for row in read_receipt["records"]:
        if row.get("channel_id") not in allowed or allowed[row["channel_id"]]!=row.get("group"):
            raise ValueError("source publisher not approved")
    payload={"receipt":read_receipt,"approved_channels":[{"id":i["id"],"group":i["group"]} for i in entries]}
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf8")
    if len(raw)>131072:raise ValueError("payload too large")
    return raw
def dispatch(raw,secret,*,url=API,now_ms=None,send=False,approved_sha=None,transport=None):
    digest=hashlib.sha256(raw).hexdigest()
    if not send:return {"mode":"DRY_RUN_NO_SEND","sha256":digest,"bytes":len(raw),"target":url}
    if not hmac.compare_digest(str(approved_sha or ""),digest):raise ValueError("explicit payload SHA-256 approval missing")
    if url!=API:raise ValueError("unreviewed receiver target")
    if len(secret)<32:raise ValueError("HMAC secret missing/short")
    stamp=str(now_ms if now_ms is not None else int(time.time()*1000))
    signature=hmac.new(secret.encode("utf8"),stamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
    request=urllib.request.Request(url,data=raw,method="POST",headers={
        "Content-Type":"application/json","X-Today-Timestamp":stamp,"X-Today-Signature":signature})
    if transport is None:
        def transport(req):
            with urllib.request.urlopen(req,timeout=20) as resp:
                return resp.status,resp.read(4096)
    try:code,body=transport(request)
    except Exception as err:raise RuntimeError("AMBIGUOUS REMOTE OUTCOME; DO NOT RETRY; inspect D1 manually") from err
    if code!=200:raise RuntimeError("NON-200 REMOTE OUTCOME; DO NOT RETRY; inspect D1 manually")
    response=json.loads(body)
    if response.get("status")!="verified" or response.get("records_verified",0)<1:
        raise RuntimeError("AMBIGUOUS ACK; DO NOT RETRY")
    return {"mode":"ONE_SHOT_REMOTE_ACK","sha256":digest,"records_verified":response["records_verified"],"status":response["status"]}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--receipt",required=True);p.add_argument("--approved-roster",required=True)
    p.add_argument("--send",action="store_true");p.add_argument("--approve-sha256")
    a=p.parse_args()
    try:
        with open(a.receipt,encoding="utf8") as f:receipt=json.load(f)
        with open(a.approved_roster,encoding="utf8") as f:roster=json.load(f)
        raw=prepare(receipt,roster)
        result=dispatch(raw,os.getenv("TODAY_PUBLISH_HMAC_SECRET",""),send=a.send,approved_sha=a.approve_sha256)
        print(json.dumps(result))
    except Exception as err:print("Today one-shot STOP: "+str(err),file=sys.stderr);raise SystemExit(1)
if __name__=="__main__":main()
