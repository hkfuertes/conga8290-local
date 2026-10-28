"""Conga 8290 map decoder — port of native/mapfile.go (decodeMap/mapJSON).

decode_file(path) / decode_bytes(data) return the same JSON shape as the Go
binary's `conga decode --json` output. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_OUT = 8 << 20


def _u16(s: str) -> int:
    return int(s, 16)


# --- header -------------------------------------------------------------
def _parse_header(h: str) -> dict:
    if len(h) < 48:
        raise ValueError("map too short")
    hd = {"version": _u16(h[0:2]), "hexlen": 48}
    if hd["version"] == 3:
        hd["hexlen"] = 52
    if len(h) < hd["hexlen"]:
        raise ValueError("map header truncated")
    hd["id"] = _u16(h[2:6])
    hd["stable"] = _u16(h[6:8]) == 1
    hd["width"] = _u16(h[8:12])
    hd["height"] = _u16(h[12:16])
    hd["origin_x"] = _u16(h[16:20]) / 10
    hd["origin_y"] = _u16(h[20:24]) / 10
    hd["resolution"] = _u16(h[24:28]) / 100
    hd["charge_x"] = _u16(h[28:32]) / 10
    hd["charge_y"] = _u16(h[32:36]) / 10
    if hd["version"] == 3:
        hd["before"] = _u16(h[40:48])
        hd["after"] = _u16(h[48:52])
    else:
        hd["before"] = _u16(h[36:44])
        hd["after"] = _u16(h[44:48])
    if hd["width"] == 0 or hd["height"] == 0 or hd["resolution"] == 0:
        raise ValueError("bad header fields")
    return hd


# --- mini-LZO1X (verbatim port of the robot-protocol decoder) -----------
def _lzo1x(src: bytes, dst: bytearray) -> int:
    n = s = 0  # n = src cursor, s = dst cursor
    srclen, dstlen = len(src), len(dst)
    while n < srclen:
        i = src[n]
        n += 1
        p = i >> 4
        if p > 0:
            m = p + 240
            while m == 255:
                if n >= srclen:
                    return s
                m = src[n]
                n += 1
                p += m
            end = n + p
            while n < end and n < srclen and s < dstlen:
                dst[s] = src[n]
                s += 1
                n += 1
            if n >= srclen:
                return s
        if n + 2 > srclen:
            return s
        d = src[n] | (src[n + 1] << 8)
        n += 2
        if d == 0 or d > s:
            return -(n - 2)  # error marker
        l = i & 15
        m = l + 240
        while m == 255:
            if n >= srclen:
                return s
            m = src[n]
            n += 1
            l += m
        u = s - d
        end = s + l + 4
        while s < end and s < dstlen:
            dst[s] = dst[u]
            s += 1
            u += 1
    return s


# --- room records after the grid ----------------------------------------
def _parse_rooms(t: bytes, version: int) -> list[dict]:
    if len(t) < 2:
        return []
    count = t[1]
    rooms = []
    n = 2
    for _ in range(count):
        if n + 47 > len(t):
            break
        u16 = lambda o: (t[n + o] << 8) | t[n + o + 1]
        name_len = t[n + 26]
        name = t[n + 27 : n + 27 + name_len].decode("utf-8", "replace") if 0 < name_len and n + 27 + name_len <= len(t) else ""
        rooms.append(
            {
                "id": u16(0),
                "order": u16(2),
                "sweep_times": u16(4),
                "mop_times": u16(6),
                "sweep_forbidden": t[n + 8] == 1,
                "mop_forbidden": t[n + 9] == 1,
                "suction": t[n + 10],
                "cistern": t[n + 11],
                "ymop": t[n + 12],
                "floor_material": t[n + 13],
                "color_order": t[n + 14],
                "name": name,
            }
        )
        n += 47 + t[n + 46] * 4
    return rooms


# --- full decode: header + grid + rooms ----------------------------------
def decode_full(raw: bytes) -> dict:
    """Everything the Go binary computes, incl. 'grid' (bytes) and 'room_pix'."""
    hexstr = raw.hex()
    hd = _parse_header(hexstr)
    cells = hd["width"] * hd["height"]

    if hd["after"] > 0:
        if hd["hexlen"] + hd["after"] * 2 > len(hexstr):
            raise ValueError("compressed blob truncated")
        comp = bytes.fromhex(hexstr[hd["hexlen"] : hd["hexlen"] + hd["after"] * 2])
        out_cap = hd["before"] * 4
        if out_cap > MAX_OUT or out_cap <= 0:
            out_cap = MAX_OUT
        dst = bytearray(out_cap)
        got = _lzo1x(comp, dst)
        if got <= 0:
            raise ValueError("lzo failed")
        out = bytes(dst[:got])
        if len(out) < cells:
            raise ValueError(f"grid short: {len(out)} < {cells}")
        grid, tail = out[:cells], out[cells:]
    else:  # uncompressed: grid directly after header
        if hd["hexlen"] + cells * 2 > len(hexstr):
            raise ValueError("uncompressed grid truncated")
        grid = bytes.fromhex(hexstr[hd["hexlen"] : hd["hexlen"] + cells * 2])
        tail = bytes.fromhex(hexstr[hd["hexlen"] + cells * 2 :])

    room_pix: dict[int, int] = {}
    if hd["version"] >= 2:
        for b in grid:
            if b & 7 in (2, 7):
                rid = (b >> 3) & 31
                room_pix[rid] = room_pix.get(rid, 0) + 1

    return {"hd": hd, "grid": grid, "rooms": _parse_rooms(tail, hd["version"]), "room_pix": room_pix}


# --- JSON shape (Go mapJSON) ---------------------------------------------
def _map_json(md: dict, bin_path: str = "", png_path: str = "") -> dict:
    hd = md["hd"]

    def w2c(px: int, py: int) -> dict:
        return {
            "X": (hd["origin_x"] - (hd["width"] - 1 - px)) * hd["resolution"] * 100,
            "Y": (hd["origin_y"] - (hd["height"] - 1 - py)) * hd["resolution"] * 100,
        }

    def w2cx(px: int) -> float:
        return (hd["origin_x"] - (hd["width"] - 1 - px)) * hd["resolution"] * 100

    def w2cy(py: int) -> float:
        return (hd["origin_y"] - (hd["height"] - 1 - py)) * hd["resolution"] * 100

    w, h, grid = hd["width"], hd["height"], md["grid"]
    bbox: dict[int, list[int]] = {}  # id -> minx, miny, maxx, maxy
    for y in range(h):
        row = y * w
        for x in range(w):
            b = grid[row + x]
            if b & 7 in (2, 7) and 1 <= (b >> 3) & 31 <= 27:
                rid = (b >> 3) & 31
                bb = bbox.get(rid)
                if bb is None:
                    bbox[rid] = [x, y, x, y]
                else:
                    if x < bb[0]:
                        bb[0] = x
                    if y < bb[1]:
                        bb[1] = y
                    if x > bb[2]:
                        bb[2] = x
                    if y > bb[3]:
                        bb[3] = y

    rooms = []
    for r in md["rooms"]:
        name = r["name"] or f"Room{r['id']}"
        zone = [0, 0, 0, 0]
        if r["id"] in bbox:
            x0, y0, x1, y1 = bbox[r["id"]]
            zone = [
                int(w2cx(x1)),
                int(w2cy(y1)),
                int(w2cx(x0) - w2cx(x1)),
                int(w2cy(y0) - w2cy(y1)),
            ]
        pix = md["room_pix"].get(r["id"], 0)
        rooms.append(
            {
                "ID": r["id"],
                "Order": r["order"],
                "Suction": r["suction"],
                "Cistern": r["cistern"],
                "SweepTimes": r["sweep_times"],
                "MopTimes": r["mop_times"],
                "FloorMaterial": r["floor_material"],
                "Pixels": pix,
                "Name": name,
                "AreaM2": pix * hd["resolution"] * hd["resolution"],
                "Zone": zone,
                "BBoxPx": bbox.get(r["id"], [0, 0, 0, 0]),  # píxeles: para la card (x0,y0,x1,y1)
            }
        )

    out = {
        "version": hd["version"],
        "map_id": hd["id"],
        "stable": hd["stable"],
        "width": w,
        "height": h,
        "resolution_m": hd["resolution"],
        "origin_x": hd["origin_x"],
        "origin_y": hd["origin_y"],
        "dock": {"x": hd["charge_x"], "y": hd["charge_y"]},
        "rooms": rooms,
        "calibration": [
            {"vacuum": w2c(0, 0), "map": {"X": 0, "Y": 0}},
            {"vacuum": w2c(w - 1, 0), "map": {"X": w - 1, "Y": 0}},
            {"vacuum": w2c(0, h - 1), "map": {"X": 0, "Y": h - 1}},
        ],
    }
    if bin_path:
        out["map_file"] = bin_path
    if png_path:
        out["png_file"] = png_path
    return out


def decode_bytes(data: bytes) -> dict:
    """Decode raw map bytes -> dict with the Go `--json` shape."""
    return _map_json(decode_full(data))


def decode_file(path: str) -> dict:
    p = Path(path)
    png = p.with_suffix(".png")
    out = _map_json(decode_full(p.read_bytes()), str(p), str(png))
    return out


# --- self-check: pixel counts learned from the Go oracle -----------------
if __name__ == "__main__":
    import glob

    # ponytail: expected {mapfile: {roomId: pixels}} from `conga decode --json`
    EXPECTED = {
        "time_1793118359_mapid_1793118358": {1: 1099, 2: 1084, 3: 1628, 4: 1329, 5: 2516, 6: 6759, 7: 1962},
        "time_1793123225_mapid_1793123236": {1: 1099, 2: 1084, 3: 1629, 4: 1329, 5: 2514, 6: 6731, 7: 1962},
        "time_1793123358_mapid_1793123369": {1: 1087, 2: 1084, 3: 1627, 4: 1331, 5: 2530, 6: 6710, 7: 1953},
    }
    files = sorted(glob.glob("maps/*.bin"))
    assert files, "no maps/*.bin found — run from repo root"
    checked = 0
    for f in files:
        d = decode_file(f)
        exp = EXPECTED.get(Path(f).stem)
        if exp is None:
            continue
        got = {r["ID"]: r["Pixels"] for r in d["rooms"]}
        assert got == exp, f"{f}: {got} != {exp}"
        checked += 1
    assert checked, "no expected map matched"
    print(f"OK: {checked} maps, room pixel counts match oracle")
