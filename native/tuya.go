// Tuya 3.3 LAN protocol over TCP 6668: AES-ECB(local_key) framing, CRC32 wrap.
package main

import (
	"crypto/aes"
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"net"
	"time"
)

const (
	cmdControl = 7  // DP write
	cmdHeart   = 9
	cmdQuery   = 10 // DP_QUERY
)

var versionHeader = append([]byte("3.3"), make([]byte, 12)...)

func ecbEncrypt(key, plain []byte) []byte {
	block, _ := aes.NewCipher(key)
	pad := 16 - len(plain)%16
	for i := 0; i < pad; i++ {
		plain = append(plain, byte(pad))
	}
	out := make([]byte, len(plain))
	for i := 0; i < len(plain); i += 16 {
		block.Encrypt(out[i:i+16], plain[i:i+16])
	}
	return out
}

func ecbDecrypt(key, ct []byte) ([]byte, error) {
	if len(ct)%16 != 0 || len(ct) == 0 {
		return nil, errors.New("bad ciphertext length")
	}
	block, _ := aes.NewCipher(key)
	out := make([]byte, len(ct))
	for i := 0; i < len(ct); i += 16 {
		block.Decrypt(out[i:i+16], ct[i:i+16])
	}
	if pad := int(out[len(out)-1]); pad >= 1 && pad <= 16 {
		if allEq(out[len(out)-pad:], byte(pad)) {
			out = out[:len(out)-pad]
		}
	}
	return out, nil
}

func allEq(b []byte, v byte) bool {
	for _, x := range b {
		if x != v {
			return false
		}
	}
	return true
}

// wrap33: 000055aa | seq | cmd | len(payload+crc+suffix) | payload | crc32 | 0000aa55
func wrap33(seq uint32, cmd int, payload []byte) []byte {
	lenWord := uint32(len(payload) + 8)
	buf := make([]byte, 16, 16+len(payload)+8)
	binary.BigEndian.PutUint32(buf[0:], 0x000055aa)
	binary.BigEndian.PutUint32(buf[4:], seq)
	binary.BigEndian.PutUint32(buf[8:], uint32(cmd))
	binary.BigEndian.PutUint32(buf[12:], lenWord)
	buf = append(buf, payload...)
	buf = append(buf, 0, 0, 0, 0)
	binary.BigEndian.PutUint32(buf[len(buf)-4:], crc32.ChecksumIEEE(buf[:len(buf)-4]))
	buf = append(buf, 0x00, 0x00, 0xaa, 0x55)
	return buf
}

// encode33 encrypts and wraps. Commands in noHeaderCmds carry no "3.3"+zeros prefix.
func encode33(key []byte, seq uint32, cmd int, jsonPayload []byte) []byte {
	enc := ecbEncrypt(key, jsonPayload)
	if cmd != cmdQuery && cmd != cmdHeart {
		enc = append(append([]byte{}, versionHeader...), enc...)
	}
	return wrap33(seq, cmd, enc)
}

type frame struct {
	cmd int
	raw []byte // payload area incl. retcode/prefix, excl. header+crc+suffix
}

// readFrames reads frames from a TCP stream until the deadline.
func readFrames(conn net.Conn, seconds int) []frame {
	var acc []byte
	deadline := time.Now().Add(time.Duration(seconds) * time.Second)
	var out []frame
	for time.Now().Before(deadline) {
		conn.SetReadDeadline(time.Now().Add(time.Duration(seconds) * time.Second))
		buf := make([]byte, 65536)
		n, err := conn.Read(buf)
		if n > 0 {
			acc = append(acc, buf[:n]...)
		}
		if err != nil {
			break
		}
		i := 0
		for i+16 <= len(acc) {
			if binary.BigEndian.Uint32(acc[i:i+4]) != 0x000055aa {
				i++
				continue
			}
			ln := int(binary.BigEndian.Uint32(acc[i+12 : i+16]))
			if ln < 8 || i+16+ln > len(acc) {
					break // partial frame; wait for more bytes
			}
			out = append(out, frame{cmd: int(binary.BigEndian.Uint32(acc[i+8 : i+12])), raw: acc[i+16 : i+16+ln-8]})
			i += 16 + ln
		}
		if i > 0 {
			acc = acc[i:]
		}
	}
	return out
}

// frameJSON decrypts a frame payload (4B retcode, optional 3.3+zeros prefix) into JSON.
func frameJSON(key []byte, f frame) (map[string]any, bool) {
	body := f.raw
	if len(body) < 4 {
		return nil, false
	}
	body = body[4:] // retcode
	if len(body) >= 15 && string(body[:3]) == "3.3" {
		body = body[15:]
	}
	dec, err := ecbDecrypt(key, body)
	if err != nil || len(dec) == 0 {
		return nil, false
	}
	var m map[string]any
	if json.Unmarshal(dec, &m) == nil {
		return m, true
	}
	// Some frames are plain text after retcode.
	if len(body) > 0 && (body[0] == '{' || body[0] == '[') {
		if json.Unmarshal(body, &m) == nil {
			return m, true
		}
	}
	return nil, false
}

func lanConnect(cfg *Config) (net.Conn, error) {
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("%s:%d", cfg.Lan.IP, cfg.Lan.Port), 6*time.Second)
	if err != nil {
		return nil, err
	}
	return conn, nil
}

// lanSend sends one command and collects decrypted dps replies for `seconds`.
func lanSend(cfg *Config, cmd int, dps map[string]any, seconds int) (map[string]any, error) {
	conn, err := lanConnect(cfg)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	key := []byte(cfg.Lan.LocalKey)
	payload := map[string]any{
		"devId": cfg.Lan.DeviceID,
		"uid":   cfg.Lan.DeviceID,
		"t":     fmt.Sprint(time.Now().Unix()),
	}
	if cmd == cmdQuery {
		payload["gwId"] = cfg.Lan.DeviceID
	} else {
		payload["dps"] = dps
	}
	js, _ := json.Marshal(payload)
	if _, err := conn.Write(encode33(key, 0, cmd, js)); err != nil {
		return nil, err
	}
	merged := map[string]any{}
	for _, f := range readFrames(conn, seconds) {
		if m, ok := frameJSON(key, f); ok {
			if d, ok := m["dps"].(map[string]any); ok {
				for k, v := range d {
					merged[k] = v
				}
			}
		}
	}
	return merged, nil
}

func lanStatus(cfg *Config) (map[string]any, error) {
	return lanSend(cfg, cmdQuery, nil, 6)
}

func lanControl(cfg *Config, dps map[string]any, seconds int) (map[string]any, error) {
	return lanSend(cfg, cmdControl, dps, seconds)
}

// b64 is used by roomclean; tiny helper to avoid importing encoding/base64 everywhere.
func b64(b []byte) string {
	const tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	var sb []byte
	for i := 0; i < len(b); i += 3 {
		var n [3]byte
		copy(n[:], b[i:])
		sb = append(sb, tbl[n[0]>>2], tbl[(n[0]&3)<<4|n[1]>>4])
		if i+1 < len(b) {
			sb = append(sb, tbl[(n[1]&15)<<2|n[2]>>6])
		} else {
			sb = append(sb, '=')
		}
		if i+2 < len(b) {
			sb = append(sb, tbl[n[2]&63])
		} else {
			sb = append(sb, '=')
		}
	}
	return string(sb)
}

var _ = rand.Reader // keep import if future use
