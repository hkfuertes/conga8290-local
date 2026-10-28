"""Conga 8290 map storage on Tuya S3 — port of cloud_probe.py + native/s3.go.

Pipeline (live-verified against ty-eu-storage-permanent.tuyaeu.com):
  storage_config(): thing.m.dev.storage.config.get v1.0 -> temporary AK/SK/token
  list_files():     thing.m.dev.common.file.list v2.0 (fileType 'pic') -> map keys
  presign_get():    query-style SigV4 presigned GET (recipe extracted from
                    libThingCloudStorageSignatureTools.so)
  download():       plain urllib GET of the presigned URL -> bytes

Notes pinned by the working Go port: the security token is the JSON field
'token' (NOT sessionToken); host is virtual-host style bucket.endpoint;
file.list keys arrive with a leading '/' that MUST be trimmed before
presigning; payload hash is the literal UNSIGNED-PAYLOAD.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import urllib.parse
import urllib.request

MAX_MAP = 32 << 20


def storage_config(cloud, dev_id: str) -> dict:
    """Temporary S3 credentials. thing.m.dev.storage.config.get — NOT file.list."""
    return cloud.call("thing.m.dev.storage.config.get", "1.0", {"type": "Common", "devId": dev_id})


def list_files(cloud, dev_id: str, gid, limit: int = 20) -> list:
    """thing.m.dev.common.file.list v2.0, fileType 'pic' (newest map files)."""
    result = cloud.call(
        "thing.m.dev.common.file.list", "2.0",
        {"devId": dev_id, "fileType": "pic", "limit": limit, "offset": 0, "gid": str(int(gid))},
    )
    return result.get("datas", []) if isinstance(result, dict) else []


def presign_get(sc: dict, key: str, expires: int = 3600, now: datetime.datetime | None = None) -> str:
    """Query-style SigV4 presigned GET URL for one S3 object key."""
    key = key.lstrip("/")  # file.list keys arrive with a leading '/'
    host = f"{sc['bucket']}.{sc['endpoint']}"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{amz_date[:8]}/{sc['region']}/s3/aws4_request"
    q = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{sc['ak']}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-Security-Token": sc["token"],
        "X-Amz-SignedHeaders": "host",
    }
    qs = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(val, safe='')}" for k, val in sorted(q.items()))
    canonical = f"GET\n/{key}\n{qs}\nhost:{host}\n\nhost\nUNSIGNED-PAYLOAD"

    def h(k: bytes, m: str) -> bytes:
        return hmac.new(k, m.encode(), hashlib.sha256).digest()

    signing = h(h(h(h(b"AWS4" + sc["sk"].encode(), amz_date[:8]), sc["region"]), "s3"), "aws4_request")
    sts = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    sig = hmac.new(signing, sts.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}/{key}?{qs}&X-Amz-Signature={sig}"


def download(url: str, timeout: float = 30.0) -> bytes:
    """Plain GET (the signature is in the query; no auth header)."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read(MAX_MAP)


def download_map(cloud, dev_id: str, gid, index: int = 0):
    """Full proven pipeline: creds -> file list -> presign -> bytes."""
    sc = storage_config(cloud, dev_id)
    files = list_files(cloud, dev_id, gid)
    if not files:
        raise RuntimeError("no map files listed")
    entry = files[index]
    return entry, download(presign_get(sc, entry["file"]))


def _self_check() -> None:
    sc = {"provider": "aws", "endpoint": "ty-eu-storage-permanent.tuyaeu.com",
          "region": "eu-central-1", "bucket": "tuya-eu-map",
          "ak": "AKIDEXAMPLE", "sk": "wJalrXUtnFEMI/K7MDENG/bPxRfiCY", "token": "tok.en=/+"}
    frozen = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    url = presign_get(sc, "/dev1/map file.png", 3600, now=frozen)
    base, query = url.split("?", 1)
    # virtual host + leading '/' trimmed + raw (unquoted) key kept as-is like the Go port
    assert base == "https://tuya-eu-map.ty-eu-storage-permanent.tuyaeu.com/dev1/map file.png", base
    q = dict(urllib.parse.parse_qsl(query))
    assert q["X-Amz-Date"] == "20260102T030405Z"
    assert q["X-Amz-Credential"] == "AKIDEXAMPLE/20260102/eu-central-1/s3/aws4_request"
    assert q["X-Amz-Security-Token"] == "tok.en=/+" and "sessionToken" not in query  # field 'token', escaped
    assert q["X-Amz-SignedHeaders"] == "host" and q["X-Amz-Expires"] == "3600"
    assert list(dict.fromkeys(k.split("=")[0] for k in query.split("&")[:-1])) == sorted(
        ["X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires", "X-Amz-Security-Token", "X-Amz-SignedHeaders"]
    )
    print("s3map.py self-check OK: presign scope/token/key-trim/param order,", q["X-Amz-Signature"])
