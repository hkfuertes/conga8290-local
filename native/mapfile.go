// Map file decode: v2 header (24B), mini-LZO grid, room records, PNG render.
// Verbatim port of @ray-js/robot-protocol's decodeMap (dist/index.js).
package main

import (
	"encoding/hex"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
	"strconv"
	"strings"
	"time"
)

type mapHeader struct {
	Version      int
	ID           int
	MapStable    bool
	Width        int
	Height       int
	OriginX      float64 // cells
	OriginY      float64
	Resolution   float64 // meters
	ChargeX      float64 // cells
	ChargeY      float64
	Before, After int   // decompressed / compressed sizes
	HeaderHexLen int
}

type roomRec struct {
	RoomID         int
	Order          int
	SweepTimes     int
	MopTimes       int
	Suction        int
	Cistern        int
	YMop           int
	FloorMaterial  int
	ColorOrder     int
	SweepForbidden bool
	MopForbidden   bool
	Name           string
}

type mapData struct {
	Header   mapHeader
	Rooms    []roomRec
	RoomPix  map[int]int // roomId -> pixel count
	Grid     []byte      // 1 byte per cell
}

func parseHeader(h string) (mapHeader, error) {
	var hd mapHeader
	if len(h) < 48 {
		return hd, fmt.Errorf("map too short")
	}
	hd.Version = hex2(h[0:2])
	hd.HeaderHexLen = 48
	if hd.Version == 3 {
		hd.HeaderHexLen = 52
	}
	if len(h) < hd.HeaderHexLen {
		return hd, fmt.Errorf("map header truncated")
	}
	hd.ID = hex4(h[2:6])
	hd.MapStable = hex2(h[6:8]) == 1
	hd.Width = hex4(h[8:12])
	hd.Height = hex4(h[12:16])
	hd.OriginX = float64(hex4(h[16:20])) / 10
	hd.OriginY = float64(hex4(h[20:24])) / 10
	hd.Resolution = float64(hex4(h[24:28])) / 100
	hd.ChargeX = float64(hex4(h[28:32])) / 10
	hd.ChargeY = float64(hex4(h[32:36])) / 10
	if hd.Version == 3 {
		hd.Before = hex8(h[40:48])
		hd.After = hex4(h[48:52])
	} else {
		hd.Before = hex8(h[36:44])
		hd.After = hex4(h[44:48])
	}
	if hd.Width == 0 || hd.Height == 0 || hd.Resolution == 0 {
		return hd, fmt.Errorf("bad header fields")
	}
	return hd, nil
}

func hex2(s string) int { v, _ := strconv.ParseUint(s, 16, 32); return int(v) }
func hex4(s string) int { v, _ := strconv.ParseUint(s, 16, 32); return int(v) }
func hex8(s string) int { v, _ := strconv.ParseUint(s, 16, 32); return int(v) }

// lzo1x: verbatim port of the minified LZO1X decoder in robot-protocol.
// src = compressed, dst = output buffer; returns bytes written.
func lzo1x(src, dst []byte) int {
	var n, s int // n = src cursor, s = dst cursor
	for n < len(src) {
		i := src[n]
		n++
		p := int(i >> 4)
		if p > 0 {
			m := p + 240
			for m == 255 {
				if n >= len(src) {
					return s
				}
				m = int(src[n])
				n++
				p += m
			}
			end := n + p
			for n < end && n < len(src) && s < len(dst) {
				dst[s] = src[n]
				s++
				n++
			}
			if n >= len(src) {
				return s
			}
		}
		if n+2 > len(src) {
			return s
		}
		d := int(src[n]) | int(src[n+1])<<8
		n += 2
		if d == 0 || d > s {
			return -(n - 2) // error marker, negative
		}
		l := int(i & 15)
		m := l + 240
		for m == 255 {
			if n >= len(src) {
				return s
			}
			m = int(src[n])
			n++
			l += m
		}
		u := s - d
		for end := s + l + 4; s < end && s < len(dst); {
			dst[s] = dst[u]
			s++
			u++
		}
	}
	return s
}

// decodeMap parses a whole .bin file (hex-level port of decodeMap).
func decodeMap(raw []byte) (*mapData, error) {
	hexStr := hex.EncodeToString(raw)
	hd, err := parseHeader(hexStr)
	if err != nil {
		return nil, err
	}
	md := &mapData{Header: hd}
	cells := hd.Width * hd.Height

	if hd.After > 0 {
		if hd.HeaderHexLen+hd.After*2 > len(hexStr) {
			return nil, fmt.Errorf("compressed blob truncated")
		}
		comp, _ := hex.DecodeString(hexStr[hd.HeaderHexLen : hd.HeaderHexLen+hd.After*2])
		outCap := hd.Before * 4
		if outCap > 8<<20 || outCap <= 0 {
			outCap = 8 << 20
		}
		dst := make([]byte, outCap)
		got := lzo1x(comp, dst)
		if got <= 0 {
			return nil, fmt.Errorf("lzo failed")
		}
		out := dst[:got]
		if len(out) < cells {
			return nil, fmt.Errorf("grid short: %d < %d", len(out), cells)
		}
		md.Grid = out[:cells]
		md.Rooms = parseRooms(out[cells:], hd.Version)
	} else {
		// uncompressed: grid directly after header
		if hd.HeaderHexLen+cells*2 > len(hexStr) {
			return nil, fmt.Errorf("uncompressed grid truncated")
		}
		g, _ := hex.DecodeString(hexStr[hd.HeaderHexLen : hd.HeaderHexLen+cells*2])
		md.Grid = g
		tail, _ := hex.DecodeString(hexStr[hd.HeaderHexLen+cells*2:])
		md.Rooms = parseRooms(tail, hd.Version)
	}

	// count room pixels: v2 cell = 3 bits type + 5 bits room
	md.RoomPix = map[int]int{}
	for _, b := range md.Grid {
		t := b & 7
		if hd.Version >= 2 && (t == 2 || t == 7) {
			md.RoomPix[int(b>>3)&31]++
		}
	}
	return md, nil
}

// parseRooms: verbatim port of `ae` (room records after the grid).
func parseRooms(t []byte, version int) []roomRec {
	if len(t) < 2 {
		return nil
	}
	count := int(t[1])
	var rooms []roomRec
	n := 2
	for i := 0; i < count && n+26+20+1 <= len(t); i++ {
		u16 := func(o int) int { return int(t[n+o])<<8 | int(t[n+o+1]) }
		r := roomRec{
			RoomID:        u16(0),
			Order:         u16(2),
			SweepTimes:    u16(4),
			MopTimes:      u16(6),
			SweepForbidden: t[n+8] == 1,
			MopForbidden:  t[n+9] == 1,
			Suction:       int(t[n+10]),
			Cistern:       int(t[n+11]),
			YMop:          int(t[n+12]),
			FloorMaterial: int(t[n+13]),
			ColorOrder:    int(t[n+14]),
		}
		nameLen := int(t[n+26])
		if nameLen > 0 && n+27+nameLen <= len(t) {
			r.Name = string(t[n+27 : n+27+nameLen])
		}
		rooms = append(rooms, r)
		n += 47 + int(t[n+46])*4
	}
	return rooms
}

var palette = []color.RGBA{
	{0xFD, 0xE4, 0xCF, 255}, {0x8E, 0xEC, 0xF5, 255}, {0xCF, 0xBA, 0xF0, 255}, {0xF1, 0xC0, 0xE8, 255},
	{0xA3, 0xC4, 0xF3, 255}, {0x98, 0xF5, 0xE1, 255}, {0xFF, 0xCF, 0xD2, 255}, {0x90, 0xDB, 0xF4, 255},
	{0xE1, 0xC1, 0xEB, 255}, {0x8E, 0xCC, 0xF5, 255}, {0xED, 0xDD, 0xDE, 255}, {0xA3, 0xB8, 0xF3, 255},
	{0xEF, 0xCF, 0xE1, 255}, {0xB2, 0xF2, 0xBE, 255}, {0xAE, 0xE6, 0xF8, 255}, {0x90, 0xC2, 0xF4, 255},
}

// renderPNG writes the grid as PNG: obstacles dark, room cells colored, dock marked.
func renderPNG(md *mapData, path string) error {
	hd := md.Header
	img := image.NewRGBA(image.Rect(0, 0, hd.Width, hd.Height))
	free := color.RGBA{0xF2, 0xF2, 0xF2, 255}
	unknown := color.RGBA{0xDD, 0xDD, 0xDD, 255}
	for i, b := range md.Grid {
		x, y := i%hd.Width, i/hd.Width
		var c color.Color
		t := b & 7
		switch {
		case hd.Version >= 2 && (t == 2 || t == 7):
			c = palette[int(b>>3)&31%16]
			if t == 2 { // carpet: darken slightly
				p := palette[int(b>>3)&31%16]
				c = color.RGBA{p.R / 2, p.G / 2, p.B / 2, 255}
			}
		case t == 1 || (hd.Version < 2 && t == 1):
			c = color.RGBA{0x55, 0x55, 0x55, 255}
		default:
			c = free
		}
		img.Set(x, y, c)
		_ = unknown
	}
	// dock marker
	dx, dy := int(hd.ChargeX+0.5), int(hd.ChargeY+0.5)
	if dx >= 0 && dx < hd.Width && dy >= 0 && dy < hd.Height {
		for _, o := range [][2]int{{0, 0}, {1, 0}, {0, 1}, {1, 1}, {-1, 0}, {0, -1}} {
			xx, yy := dx+o[0], dy+o[1]
			if xx >= 0 && xx < hd.Width && yy >= 0 && yy < hd.Height {
				img.Set(xx, yy, color.RGBA{0x00, 0x66, 0xFF, 255})
			}
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

func summarize(md *mapData) string {
	hd := md.Header
	var b strings.Builder
	fmt.Fprintf(&b, "map v%d id=%d %dx%d (%.1fx%.1f m) res=%.2fm dock=(%.1f,%.1f) stable=%v",
		hd.Version, hd.ID, hd.Width, hd.Height,
		float64(hd.Width)*hd.Resolution, float64(hd.Height)*hd.Resolution,
		hd.Resolution, hd.ChargeX, hd.ChargeY, hd.MapStable)
	if len(md.Rooms) > 0 {
		b.WriteString("\nrooms:")
		for _, r := range md.Rooms {
			name := r.Name
			if name == "" {
				name = fmt.Sprintf("Room%d", r.RoomID)
			}
			fmt.Fprintf(&b, "\n  id=%d %-20s order=%d suction=%d cistern=%d sweep=%dx mop=%dx floor=%d pixels=%d (%.1f m²)",
				r.RoomID, name, r.Order, r.Suction, r.Cistern, r.SweepTimes, r.MopTimes,
				r.FloorMaterial, md.RoomPix[r.RoomID],
				float64(md.RoomPix[r.RoomID])*hd.Resolution*hd.Resolution)
		}
	}
	return b.String()
}

// decodeFile: full offline pipeline for one .bin.
func decodeFile(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	md, err := decodeMap(raw)
	if err != nil {
		return "", err
	}
	if err := renderPNG(md, strings.TrimSuffix(path, ".bin")+".png"); err != nil {
		return "", err
	}
	return summarize(md), nil
}

// getMap: LAN get_both -> wait for upload -> list -> download -> decode -> PNG.
func getMap(cfg *Config, waitSeconds int, outdir string) (string, string, error) {
	if _, err := lanControl(cfg, map[string]any{"16": "get_both"}, 4); err != nil {
		return "", "", fmt.Errorf("LAN get_both: %w", err)
	}
	fmt.Printf("get_both sent; waiting %ds for cloud upload…\n", waitSeconds)
	time.Sleep(time.Duration(waitSeconds) * time.Second)

	sc, err := getStorageConfig(cfg)
	if err != nil {
		return "", "", err
	}
	files, err := listMapFiles(cfg, 5)
	if err != nil {
		return "", "", err
	}
	if len(files) == 0 {
		return "", "", fmt.Errorf("no map files in cloud")
	}
	newest := files[0]
	key := strings.TrimPrefix(newest.File, "/")
	data, err := download(sc, key)
	if err != nil {
		return "", "", err
	}
	if err := os.MkdirAll(outdir, 0o755); err != nil {
		return "", "", err
	}
	name := newest.File[strings.LastIndex(newest.File, "/")+1:]
	path := outdir + "/" + name
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return "", "", err
	}
	md, err := decodeMap(data)
	if err != nil {
		return path, "", fmt.Errorf("downloaded ok but decode failed: %w", err)
	}
	if err := renderPNG(md, strings.TrimSuffix(path, ".bin")+".png"); err != nil {
		return path, "", err
	}
	when := time.Unix(newest.Time, 0).Format("2006-01-02 15:04")
	return path, "cloud entry: " + when + "\n" + summarize(md), nil
}
