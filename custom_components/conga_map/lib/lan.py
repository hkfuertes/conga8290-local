"""Conga 8290 LAN via Tuya 3.3 (tinytuya-compatible wire format; port of a removed prototype).

Short-lived connections only: one connect per request, never persistent.
Framing (tinytuya 3.3 and the Go port cross-checked, live-verified on the 8290):

  wrap    = 000055aa | seq | cmd | len(payload+crc32+suffix) | payload | crc32 | 0000aa55
  CONTROL (0x07) payload = b"3.3" + 12 NULs + AES-ECB(local_key, json)   # prefix in the clear
  DP_QUERY (0x0a) payload = AES-ECB(local_key, json)                     # no version prefix
  response payload = 4-byte retcode | optional b"3.3"+12 NULs | AES-ECB(json)

JSON must have ALL spaces stripped (tinytuya: "if spaces are not removed
device does not respond!"). Uses `cryptography` AES; manual PKCS7 pad/unpad.
"""
from __future__ import annotations

import json
import socket
import time
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PREFIX = b"\x00\x00\x55\xaa"
SUFFIX = b"\x00\x00\xaa\x55"
V33 = b"3.3" + b"\x00" * 12
CONTROL = 0x07
DP_QUERY = 0x0A


def _pad(b: bytes) -> bytes:
    n = 16 - len(b) % 16
    return b + bytes((n,)) * n


def _unpad(b: bytes) -> bytes:
    n = b[-1] if b else 0
    return b[:-n] if 1 <= n <= 16 and b[-n:] == bytes((n,)) * n else b


def _ecb_encrypt(key: bytes, plaintext: bytes) -> bytes:
    op = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return op.update(_pad(plaintext)) + op.finalize()


def _ecb_decrypt(key: bytes, ciphertext: bytes) -> bytes:
    op = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return _unpad(op.update(ciphertext) + op.finalize())


def _wrap(cmd: int, payload: bytes, seq: int = 0) -> bytes:
    head = PREFIX + seq.to_bytes(4, "big") + cmd.to_bytes(4, "big") + (len(payload) + 8).to_bytes(4, "big")
    body = head + payload
    return body + zlib.crc32(body).to_bytes(4, "big") + SUFFIX


def _payloads(buf: bytes):
    """Yield (cmd, payload-area) for every 55aa frame found in a receive buffer."""
    i = 0
    while i + 16 <= len(buf):
        if buf[i : i + 4] != PREFIX:
            i += 1
            continue
        ln = int.from_bytes(buf[i + 12 : i + 16], "big")
        if ln < 8 or i + 16 + ln > len(buf):  # partial/corrupt: resync one byte
            i += 1
            continue
        yield int.from_bytes(buf[i + 8 : i + 12], "big"), buf[i + 16 : i + 16 + ln - 8]
        i += 16 + ln


def _decode(key: bytes, body: bytes) -> dict | None:
    """retcode | optional 3.3 prefix | ECB ciphertext -> JSON dict (or None)."""
    if len(body) < 4:
        return None
    body = body[4:]  # 4-byte cleartext return code
    if len(body) >= 15 and body[:3] == b"3.3":
        body = body[15:]
    if not body or len(body) % 16:
        return None
    try:
        text = _ecb_decrypt(key, body).decode("utf8", "replace")
        end = text.rfind("}")  # robot firmware can trail garbage after the JSON
        return json.loads(text[: end + 1]) if end >= 0 else None
    except Exception:
        return None


class CongaLAN:
    """Tuya 3.3 LAN client for one Conga robot; one short-lived TCP connection per call."""

    def __init__(self, device_id: str, host: str, local_key: str, port: int = 6668, timeout: float = 6.0):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.timeout = timeout
        self._key = local_key.encode()

    def _request(self, cmd: int, dps: dict | None, listen: float) -> dict:
        payload = {"devId": self.device_id, "uid": self.device_id, "t": str(int(time.time()))}
        if cmd == DP_QUERY:
            payload["gwId"] = self.device_id
        else:
            payload["dps"] = dps
        enc = _ecb_encrypt(self._key, json.dumps(payload).replace(" ", "").encode())
        if cmd != DP_QUERY:
            enc = V33 + enc  # version header travels in the clear (tinytuya 3.3)
        buf = b""
        with socket.create_connection((self.host, self.port), self.timeout) as sock:
            sock.sendall(_wrap(cmd, enc))
            deadline = time.monotonic() + listen
            while time.monotonic() < deadline:
                sock.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    chunk = sock.recv(65536)
                except OSError:  # timeout / reset: we only wanted short-lived reads
                    break
                if not chunk:
                    break
                buf += chunk
        merged: dict = {}
        for _, body in _payloads(buf):
            for k, v in (_decode(self._key, body) or {}).get("dps", {}).items():
                merged[k] = v
        return merged

    def status(self, listen: float = 3.0) -> dict:
        """DP_QUERY (cmd 0x0a); returns the merged dps dict."""
        return self._request(DP_QUERY, None, listen)

    def send_dps(self, dps: dict, listen: float = 3.0) -> dict:
        """CONTROL (cmd 0x07) with devId/uid/t; returns dps seen in the replies."""
        return self._request(CONTROL, dps, listen)

    def trigger_get_both(self, listen: float = 3.0) -> dict:
        """Ask the robot to upload map+path to the cloud (DP16 'get_both')."""
        return self.send_dps({"16": "get_both"}, listen)


def _self_check() -> None:
    key = b"0123456789abcdef"
    for n in (1, 15, 16, 17, 33):  # ECB + manual PKCS7 roundtrip, fake key
        blob = bytes(range(n))
        assert _ecb_decrypt(key, _ecb_encrypt(key, blob)) == blob
    # full response frame: retcode + 3.3 prefix + ciphertext -> dps merge
    inner = json.dumps({"dps": {"15": "YWJj", "5": "standby"}}).encode()
    frame = _wrap(CONTROL, b"\x00\x00\x00\x00" + V33 + _ecb_encrypt(key, inner))
    merged = {}
    for _, body in _payloads(frame):
        for k, v in (_decode(key, body) or {}).get("dps", {}).items():
            merged[k] = v
    assert merged == {"15": "YWJj", "5": "standby"}, merged
    head = _wrap(DP_QUERY, b"")
    assert head[:4] == PREFIX and head[-4:] == SUFFIX
    assert int.from_bytes(head[12:16], "big") == 8  # len word = crc+suffix only
    print("lan.py self-check OK: ecb roundtrip, frame wrap/unwrap, dps merge")
