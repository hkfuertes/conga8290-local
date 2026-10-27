#!/usr/bin/env python3
"""Sniff all LAN pushes from the robot while the app sends commands.

Logs every decrypted DPS push with timestamps; highlights DP15 frames
(robot protocol: room clean 0x14, zone 0x3a, ...). Reconnects forever.
Stops after --duration seconds (default 600).
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
KEY = b"REDACTED_LOCAL_KEY"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 600
OUT = open("/tmp/app_sniff.log", "a", buffering=1)


def ts():
    return time.strftime("%H:%M:%S")


def parse_frames(buf):
    """Yield (cmd, payload) 3.3 frames from buffer; return consumed offset."""
    i = 0
    out = []
    while i + 16 <= len(buf):
        if buf[i : i + 4] != b"\x00\x00\x55\xaa":
            i += 1
            continue
        ln = int.from_bytes(buf[i + 12 : i + 16], "big")
        if i + 16 + ln + 8 > len(buf):
            break
        fr = buf[i : i + 16 + ln + 8]
        out.append((fr[8 + 4], bytes(fr[35 : 16 + ln - 8])))
        i += 16 + ln + 8
    return out, i


def dps_of(payload):
    if not payload or len(payload) % 16:
        return None
    pt = AES.new(KEY, AES.MODE_ECB).decrypt(payload)
    pad = pt[-1]
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    s = pt.decode("utf8", "replace")
    try:
        return json.loads(s[: s.rfind("}") + 1]).get("dps", {})
    except Exception:
        return None


def show(dps):
    for k, v in dps.items():
        if k == "15" and isinstance(v, str):
            b = base64.b64decode(v)
            OUT.write(f"{ts()} DP15 {len(b)}B {b.hex()}\n")
            print(f"{ts()} DP15 {len(b)}B {b.hex()}")
        elif k in ("1", "4", "5", "6", "16", "107"):
            if k == "107" and isinstance(v, str):
                b = base64.b64decode(v)
                if b.strip(b"\x00"):
                    OUT.write(f"{ts()} DP107 NONZERO {b.hex()}\n")
                    print(f"{ts()} DP107 NONZERO {b.hex()}")
            elif k != "107":
                OUT.write(f"{ts()} DP{k} = {v}\n")
                print(f"{ts()} DP{k} = {v}")


t0 = time.time()
while time.time() - t0 < DURATION:
    try:
        d = tinytuya.Device(DEVICE_ID, ADDRESS, KEY.decode())
        d.set_version(3.3)
        d.set_socketPersistent(True)
        d.set_socketTimeout(8)
        d.heartbeat()
        OUT.write(f"{ts()} === connected\n")
        print(f"{ts()} === connected", flush=True)
        d.socket.settimeout(10)
        buf = b""
        while time.time() - t0 < DURATION:
            try:
                data = d.socket.recv(65536)
            except socket.timeout:
                try:
                    d.heartbeat()
                except Exception:
                    break
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            frames, used = parse_frames(buf)
            buf = buf[used:]
            for cmd, payload in frames:
                dps = dps_of(payload)
                if dps:
                    show(dps)
    except Exception as e:
        print(f"{ts()} reconnect ({e})", flush=True)
        time.sleep(3)
OUT.write(f"{ts()} === sniff window over\n")
print(f"{ts()} === done")
