#!/usr/bin/env python3
"""Conga 8290 LAN control via Tuya 3.3 (tinytuya).

Verified live: status, start/stop/return, DP16 get_both live stream,
DP15 `command_trans` robot-protocol frames (Tuya laser robot protocol,
see @ray-js/robot-protocol). The robot answered 0x13 (virtual wall data)
with frame `aa0100000002130013` (V1 framing: AA 01 <len:4> <payload> <cksum>).

Map bytes are NOT pushed over LAN (only pose via DP15 cmd 0x39 and an empty
DP107 keepalive); the map file goes to the cloud after DP16 get_both.

Usage:
  python3 conga_lan.py status
  python3 conga_lan.py send15 <hexframe>       # raw DP15 frame, hex
  python3 conga_lan.py req <cmdhex>            # build+send V1 request, listen
  python3 conga_lan.py roomclean <id>... [-p N]# 0x14 room clean (moves robot!)
  python3 conga_lan.py get_both [seconds]      # open live stream, dump frames
"""
import base64
import json
import socket
import sys
import time

import tinytuya
from Crypto.Cipher import AES

DEVICE_ID = "REDACTED_DEVICE_ID"
ADDRESS = "192.168.0.239"
LOCAL_KEY = "REDACTED_LOCAL_KEY"


def connect(persistent=True):
    d = tinytuya.Device(DEVICE_ID, ADDRESS, LOCAL_KEY)
    d.set_version(3.3)
    d.set_socketPersistent(persistent)
    d.set_socketTimeout(6)
    return d


def v1_frame(payload: bytes) -> bytes:
    """App->robot frame, version 1 (4-byte length), as the device replies with."""
    return bytes([0xAA, 1, 0, 0, 0, len(payload)]) + payload + bytes([sum(payload) & 0xFF])


def decrypt_frames(raw: bytes):
    """Yield decrypted JSON payloads from a raw 3.3 TCP buffer."""
    i = 0
    while i + 16 <= len(raw):
        if raw[i : i + 4] != b"\x00\x00\x55\xaa":
            i += 1
            continue
        ln = int.from_bytes(raw[i + 12 : i + 16], "big")
        fr = raw[i : i + 16 + ln + 8]
        i += 16 + ln + 8
        data = bytes(fr[35 : 16 + ln - 8])
        if not data or len(data) % 16:
            continue
        pt = AES.new(LOCAL_KEY.encode(), AES.MODE_ECB).decrypt(data)
        pad = pt[-1]
        if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
            pt = pt[:-pad]
        try:
            yield json.loads(pt.decode("utf8")[: pt.decode("utf8", "replace").rfind("}") + 1])
        except Exception:
            continue


def listen(d, seconds, on_dps=None):
    raw = b""
    t0 = time.time()
    d.socket.settimeout(seconds)
    while time.time() - t0 < seconds:
        try:
            data = d.socket.recv(65536)
        except (socket.timeout, OSError):
            break
        if not data:
            break
        raw += data
    for msg in decrypt_frames(raw):
        for k, v in (msg.get("dps") or {}).items():
            if on_dps:
                on_dps(k, v)
            elif k in ("15", "107") and isinstance(v, str):
                b = base64.b64decode(v)
                print(f"DP{k} <- {len(b)}B {b.hex()[:120]}{'...' if len(b) > 60 else ''}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    d = connect()
    if cmd == "status":
        st = d.status()["dps"]
        print("status:", st.get("5"), "| mode:", st.get("4"), "| batt%:", st.get("6"))
    elif cmd == "send15":
        d.heartbeat()
        d.send(d.generate_payload(tinytuya.CONTROL, {"15": sys.argv[2]}))
        listen(d, 5)
    elif cmd == "req":
        hx = sys.argv[2]
        payload = bytes.fromhex(hx)
        frame = v1_frame(payload)
        d.heartbeat()
        d.send(d.generate_payload(tinytuya.CONTROL, {"15": base64.b64encode(frame).decode()}))
        print("sent", frame.hex())
        listen(d, 6)
    elif cmd == "roomclean":
        ids = [int(a) for a in sys.argv[2:] if not a.startswith("-p")]
        passes = 1
        if "-p" in sys.argv:
            passes = int(sys.argv[sys.argv.index("-p") + 1])
        payload = bytes([0x14, passes, len(ids), *ids])
        frame = v1_frame(payload)
        d.heartbeat()
        d.send(d.generate_payload(tinytuya.CONTROL, {"15": base64.b64encode(frame).decode()}))
        d.send(d.generate_payload(tinytuya.CONTROL, {"4": "select_room"}))
        print("sent roomclean", frame.hex())
    elif cmd == "get_both":
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        d.heartbeat()
        d.send(d.generate_payload(tinytuya.CONTROL, {"16": "get_both"}))
        listen(d, secs)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
