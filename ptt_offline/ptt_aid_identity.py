"""PTT AIDv1 identity verification from canonical article filename.

PTT's published AIDv1 mapping encodes the M.<epoch>.A.<hex> filename
into eight digits using alphabet 0-9 A-Z a-z - _ (6 bits per digit).
Canonical identity is derived independently from the supplied URL string,
not from an injected boolean claim. Offline only; no network or source DB.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from .public_today_contract import ContractError, normalize_public_aid

ALPHABET="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
URL_RE=re.compile(r"^https://www\.ptt\.cc/bbs/(?P<board>[A-Za-z0-9_-]+)/M\.(?P<epoch>[0-9]{9,10})\.A\.(?P<suffix>[0-9A-Fa-f]{3})\.html$")

def aid_from_article_url(url: str) -> tuple[str,str]:
    match=URL_RE.fullmatch(url or "")
    if not match:
        raise ContractError("invalid canonical PTT article URL")
    epoch=int(match.group("epoch"))
    if not 0 < epoch < (1<<31):
        raise ContractError("invalid PTT filename epoch")
    suffix=int(match.group("suffix"),16)
    # AIDv1 = 31-bit filename seconds followed by 12-bit suffix.
    value=(epoch<<12)|suffix
    encoded="".join(ALPHABET[(value>>(6*index))&63] for index in range(7,-1,-1))
    return match.group("board"),encoded

def verify_aid_url(board: str,aid: str,url: str) -> bool:
    try:
        parsed_board,derived=aid_from_article_url(url)
        return board==parsed_board and normalize_public_aid(aid)==derived
    except (ContractError,TypeError,ValueError):
        return False

def identity_receipt(board: str,aid: str,url: str) -> dict:
    if not verify_aid_url(board,aid,url):
        raise ContractError("PTT AID and canonical filename mismatch")
    canonical=normalize_public_aid(aid)
    evidence={"board":board,"aid":canonical,"url":url,
              "authority":"ptt-aidv1-filename-bijective","version":1}
    evidence["digest"]=sha256(json.dumps(evidence,sort_keys=True,
        separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    return evidence
