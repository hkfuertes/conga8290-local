"""Cecotec OEM cloud client (a1.tuyaeu.com /api.json) — compact port of
conga8290/{cloud_protocol,oem_auth_request,oem_candidate_request,
oem_readonly_api,oem_login_payload,oem_rootless_client}.py + native/{cloud,login}.go
(cloud_probe.py flow), live-verified with the Cecotec app's own credentials.

Request shape (ET3): form-encoded POST; postData = base64(12B nonce +
AES-GCM seal of the compact JSON payload); sign = HMAC-SHA256(material,
'||'-joined sorted signed fields, postData substituted by the SDK's
rearranged MD5: d[8:16]+d[:8]+d[24:]+d[16:24]).

Request key = first 16 ASCII-hex chars of HMAC-SHA256(key=requestId,
material + b'_' + ecode). AUTH requests (token/login) carry NO sid and
derive the key WITHOUT the ecode suffix — None and '' differ in the SDK.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import ssl
import time
import uuid
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API_HOST = "a1.tuyaeu.com"  # only OEM gateway verified for this account/app
CONGA_PRODUCT = "kofl9ubyyyfznpxw"

# Static app identity from the pinned Cecotec 1.2.9 APK (native/extract.go,
# conga8290/oem_bootstrap_fixture.py). MATERIAL decodes to
#   package _ SHA256(signing-cert) fingerprint (uppercase hex, ':' pairs)
#   _ carrier key (assets/t_s.bmp) _ appSecret (BuildConfig dex statics)
MATERIAL_HEX = (
    "65732e6365636f7465632e666f726365636c696d615f45393a33423a41343a43373a33313a38423a42383a33463a32393a36443a35383a33333a42413a39463a46423a35343a46463a43433a31343a41413a44463a38313a45463a43363a44413a44383a38373a41423a36463a46443a37313a34325f"
    "6b75656a6161656a616667636e677566633433647665636738717879786333665f"
    "776a3772787470676b666a336a786637736a667439396b636b6a76346863636b"
)
MATERIAL = bytes.fromhex(MATERIAL_HEX)
# ch_key = HMAC-SHA256(key=CLIENT_ID, msg=package + "_" + fingerprint).hexdigest()[8:16]
# (fingerprint = the colon-separated uppercase SHA-256 embedded in MATERIAL;
# validated against the native ELF getChKey and by live cloud acceptance)
CH_KEY = "a08d27b6"
CLIENT_ID = "4vkmwtftwghwddvhcpjv"
APP_VERSION = "1.2.9"
TTID = "sdk_international@4vkmwtftwghwddvhcpjv"

# ThingApiSignManager: the SDK signs only these params (alphabetical; no 'cp').
SIGNED_FIELDS = (
    "a", "appVersion", "chKey", "clientId", "deviceId", "et", "h5Token",
    "isH5", "lang", "lat", "lon", "n4h5", "os", "postData", "requestId",
    "sid", "sp", "time", "ttid", "v",
)
MAX_RESPONSE = 8 << 20


def _postdata_hash(postdata: str) -> str:
    d = hashlib.md5(postdata.encode()).hexdigest()
    return d[8:16] + d[:8] + d[24:] + d[16:24]


def _request_key(request_id: str, ecode: str | None = None) -> bytes:
    message = MATERIAL if ecode is None else MATERIAL + b"_" + ecode.encode()
    return hmac.new(request_id.encode(), message, hashlib.sha256).hexdigest()[:16].encode()


def _et3_encrypt(key: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, None)).decode()


def _et3_decrypt(key: bytes, encoded: str) -> bytes:
    packet = base64.b64decode(encoded, validate=True)
    if len(packet) < 28:
        raise RuntimeError("et3 envelope too short")
    return AESGCM(key).decrypt(packet[:12], packet[12:], None)


def _sign(body: dict) -> str:
    parts = [
        f"{name}={_postdata_hash(body[name]) if name == 'postData' else body[name]}"
        for name in SIGNED_FIELDS
        if body.get(name)
    ]
    return hmac.new(MATERIAL, "||".join(parts).encode(), hashlib.sha256).hexdigest()


def _gunzip(data: bytes) -> bytes:
    if len(data) > MAX_RESPONSE:
        raise RuntimeError("response budget exceeded")
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def _decode(envelope: dict, key: bytes, depth: int = 0):
    """Business envelope (MD5 + ET3, recursive) then success/result."""
    if depth > 2:
        raise RuntimeError("envelope recursion too deep")
    if "success" not in envelope and isinstance(envelope.get("result"), str):
        result, sign, t = envelope["result"], envelope.get("sign"), envelope.get("t")
        if not result or not isinstance(sign, str) or not isinstance(t, int):
            raise RuntimeError("unreadable encrypted business envelope")
        canonical = f"result={result}||t={t}||".encode() + key
        if not hmac.compare_digest(hashlib.md5(canonical).hexdigest(), sign.lower()):
            raise RuntimeError("business response signature invalid")
        return _decode(json.loads(_gunzip(_et3_decrypt(key, result))), key, depth + 1)
    if envelope.get("success") is not True:
        raise RuntimeError(f"gateway error {envelope.get('errorCode')}: {envelope.get('errorMsg')}")
    result = envelope.get("result")
    if isinstance(result, str):
        if result.lstrip()[:1] in "[{":
            return json.loads(result)
        return json.loads(_gunzip(_et3_decrypt(key, result)))
    return result


def _post(api_url: str, body: dict) -> dict:
    request = Request(
        f"https://{api_url}/api.json",
        data=urlencode(body).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept-Encoding": "gzip"},
    )
    # signed bodies must never leak via environment proxies
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=25) as response:
        raw = response.read(MAX_RESPONSE)
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


class OEMCloud:
    """OEM gateway client: login() once, then call()/homes()/devices().

    Non-auth calls need the session; auth calls (username token, password
    login) send no sid and derive their key without the ecode suffix.
    """

    def __init__(self, phone_id: str | None = None):
        self.phone_id = phone_id or secrets.token_hex(22)  # random install id
        self.sid: str | None = None
        self.ecode: str | None = None
        self.api_url = API_HOST

    def call(self, method: str, version: str, payload, *, auth: bool = False):
        if not auth and not self.sid:
            raise RuntimeError("login() required before session calls")
        request_id = str(uuid.uuid4())
        key = _request_key(request_id, None if auth else self.ecode)
        body = {
            "clientId": CLIENT_ID, "appVersion": APP_VERSION, "ttid": TTID,
            "deviceId": self.phone_id, "os": "Android", "lang": "en",
            "et": "3", "cp": "gzip", "chKey": CH_KEY, "requestId": request_id,
            "time": str(int(time.time())), "a": method, "v": version,
            "postData": _et3_encrypt(key, json.dumps(payload, separators=(",", ":")).encode()),
        }
        if not auth:
            body["sid"] = self.sid  # auth bodies carry no sid
        body["sign"] = _sign(body)
        return _decode(_post(self.api_url, body), key)

    def login(self, country_code: str, email: str, password: str) -> bool:
        """oem-ui flow: username token (v2.0) -> RSA password login (v3.0)."""
        token = self.call(
            "smartlife.m.user.username.token.get", "2.0",
            {"countryCode": country_code, "username": email, "isUid": False}, auth=True,
        )
        modulus, exponent = token.get("publicKey"), token.get("exponent")
        if not isinstance(token.get("token"), str) or not isinstance(modulus, str) or not isinstance(exponent, str):
            raise RuntimeError("username token missing RSA fields")
        digest = hashlib.md5(password.encode()).hexdigest()
        public = rsa.RSAPublicNumbers(int(exponent), int(modulus)).public_key()
        session = self.call(
            "smartlife.m.user.email.password.login", "3.0",
            {
                "countryCode": country_code, "email": email,
                "passwd": public.encrypt(digest.encode(), padding.PKCS1v15()).hex(),
                "token": token["token"], "ifencrypt": 1,
                "options": '{"group":1,"mfaCode": ""}',
            },
            auth=True,
        )
        self.sid, self.ecode = session["sid"], session["ecode"]
        domain = session.get("domain") or {}
        # ponytail: only a1.tuyaeu.com is verified; any other routed host is ignored
        if API_HOST in str(domain.get("mobileApiUrl", "")):
            self.api_url = API_HOST
        return True

    def homes(self) -> list:
        """m.life.home.space.list v1.0 (needs login)."""
        return self.call("m.life.home.space.list", "1.0", {}) or []

    def devices(self, gid) -> list:
        """m.life.my.group.device.list v2.2; unwrapped device dicts."""
        result = self.call("m.life.my.group.device.list", "2.2", {"gid": str(int(gid))})
        if isinstance(result, dict):
            result = result.get("devices", result.get("list"))
        return result or []


def _self_check() -> None:
    parts = MATERIAL.split(b"_")
    assert len(parts) == 4, "material segments"
    text = MATERIAL.decode("ascii")
    assert text.startswith("es.cecotec.forceclima_")
    secret = parts[3].decode()
    assert secret == "wj7rxtpgkfj3jxf7sjft99kckjv4hcck" and len(secret) == 32
    # documented formula: HMAC-SHA256(key=CLIENT_ID, package+"_"+fingerprint)[8:16]
    assert hmac.new(CLIENT_ID.encode(), parts[0] + b"_" + parts[1], hashlib.sha256).hexdigest()[8:16] == CH_KEY
    key = b"0123456789abcdef"
    assert _et3_decrypt(key, _et3_encrypt(key, b'{"dps":{}}')) == b'{"dps":{}}'
    d = hashlib.md5(b"hello").hexdigest()  # rearranged MD5, not plain
    assert _postdata_hash("hello") == d[8:16] + d[:8] + d[24:] + d[16:24]
    assert _request_key("rid") != _request_key("rid", "")  # None vs '' ecode differ
    # encrypted business envelope: MD5(result||t||key) + ET3 + recursion
    inner = json.dumps({"success": True, "result": [1, 2]}).encode()
    ct = _et3_encrypt(key, inner)
    sign = hashlib.md5(f"result={ct}||t={1700000000}||".encode() + key).hexdigest()
    assert _decode({"result": ct, "sign": sign.upper(), "t": 1700000000}, key) == [1, 2]
    print("cloud.py self-check OK: material, ch_key formula, et3 roundtrip, md5 sign, envelope decode")
