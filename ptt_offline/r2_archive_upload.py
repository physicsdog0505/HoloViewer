"""Upload an exported PTT archive directory to an existing Cloudflare R2 bucket.

Fail closed by default. --apply is required. Chunk objects are uploaded with
immutable caching; the manifest is uploaded last so readers never observe a
manifest that references objects not yet present.
"""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

def run(cmd):
    print("+"," ".join(map(str,cmd)),flush=True)
    return subprocess.run(cmd,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--apply",action="store_true")
    args=p.parse_args(argv)
    if not args.apply:
        raise SystemExit("refusing R2 mutation without --apply")

    root=Path(args.root).resolve(strict=True)
    manifest_path=(root/args.manifest).resolve(strict=True)
    if root not in manifest_path.parents:
        raise SystemExit("manifest must be inside export root")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    objects=manifest.get("objects")
    if not isinstance(objects,list) or not objects:
        raise SystemExit("manifest has no archive objects")

    # Bucket must already exist. Do not create/delete buckets implicitly.
    listed=run(["npx","wrangler","r2","bucket","list"]).stdout
    if args.bucket not in listed:
        raise SystemExit("target R2 bucket not found: "+args.bucket)

    uploaded=0
    for item in objects:
        key=item.get("key")
        if not isinstance(key,str) or not key.startswith("ptt/v1/chunks/") or ".." in key:
            raise SystemExit("invalid object key in manifest")
        source=(root/key).resolve(strict=True)
        if root not in source.parents:
            raise SystemExit("object escaped export root")
        run([
            "npx","wrangler","r2","object","put",f"{args.bucket}/{key}",
            "--remote","--file",str(source),
            "--content-type","application/json",
            "--content-encoding","gzip",
            "--cache-control","public,max-age=31536000,immutable",
        ])
        uploaded+=1

    manifest_key=str(manifest_path.relative_to(root))
    run([
        "npx","wrangler","r2","object","put",f"{args.bucket}/{manifest_key}",
        "--remote","--file",str(manifest_path),
        "--content-type","application/json",
        "--cache-control","public,max-age=60",
    ])

    # Verify first + last chunk and the manifest can be read back remotely.
    probes=[objects[0]["key"],objects[-1]["key"],manifest_key]
    verify_dir=root/".r2-verify"
    verify_dir.mkdir(exist_ok=True)
    for index,key in enumerate(probes):
        target=verify_dir/f"probe-{index}"
        run([
            "npx","wrangler","r2","object","get",f"{args.bucket}/{key}",
            "--remote","--file",str(target),
        ])
        if target.stat().st_size<=0:
            raise SystemExit("empty R2 readback: "+key)

    print(json.dumps({
        "status":"R2_ARCHIVE_UPLOADED",
        "bucket":args.bucket,
        "objects_uploaded":uploaded,
        "manifest_key":manifest_key,
        "readback_probes":probes,
    },ensure_ascii=False))

if __name__=="__main__": main()
