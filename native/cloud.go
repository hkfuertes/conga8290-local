// Cecotec OEM cloud gateway (a1.tuyaeu.com /api.json): ET3 AES-GCM envelope,
// HMAC-SHA256 signing, rearranged-MD5 postData hash, recursive result decode.
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

var signedFields = []string{ // alphabetical, mirrors the SDK's SIGNED_FIELDS
	"a", "appVersion", "chKey", "clientId", "deviceId", "et", "h5Token",
	"isH5", "lang", "lat", "lon", "n4h5", "os", "postData", "requestId",
	"sid", "sp", "time", "ttid", "v",
}

// rearranged MD5: d[8:16]+d[0:8]+d[24:]+d[16:24]
func postdataHash(s string) string {
	d := md5.Sum([]byte(s))
	h := hex.EncodeToString(d[:])
	return h[8:16] + h[0:8] + h[24:] + h[16:24]
}

func material(cfg *Config) []byte {
	m, err := hex.DecodeString(cfg.Static.MaterialHex)
	if err != nil || len(m) == 0 {
		fatalIf(fmt.Errorf("bad material_hex in config"), "material")
	}
	return m
}

// requestKey: first 16 hex-ASCII chars of HMAC-SHA256(key=requestId, msg=material+"_"+ecode).
// Pre-login (auth) requests append NO suffix — None and "" differ in the SDK.
func requestKey(cfg *Config, requestID string) []byte {
	mac := hmac.New(sha256.New, []byte(requestID))
	mac.Write(append(append([]byte{}, material(cfg)...), []byte("_"+cfg.Session.Ecode)...))
	return []byte(hex.EncodeToString(mac.Sum(nil))[:16])
}

func requestKeyAuth(cfg *Config, requestID string) []byte {
	mac := hmac.New(sha256.New, []byte(requestID))
	mac.Write(material(cfg))
	return []byte(hex.EncodeToString(mac.Sum(nil))[:16])
}

func et3Encrypt(key, plain []byte) string {
	block, _ := aes.NewCipher(key)
	gcm, _ := cipher.NewGCM(block)
	nonce := make([]byte, gcm.NonceSize())
	rand.Read(nonce)
	return base64.StdEncoding.EncodeToString(gcm.Seal(nonce, nonce, plain, nil))
}

func et3Decrypt(key []byte, encoded string) ([]byte, error) {
	packet, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil || len(packet) < 28 {
		return nil, fmt.Errorf("bad et3 packet")
	}
	block, _ := aes.NewCipher(key)
	gcm, _ := cipher.NewGCM(block)
	return gcm.Open(nil, packet[:12], packet[12:], nil)
}

func signBody(cfg *Config, body map[string]string) string {
	var buf bytes.Buffer
	for _, f := range signedFields {
		v, ok := body[f]
		if !ok || v == "" {
			continue
		}
		if f == "postData" {
			v = postdataHash(v)
		}
		if buf.Len() > 0 {
			buf.WriteString("||")
		}
		buf.WriteString(f + "=" + v)
	}
	mac := hmac.New(sha256.New, material(cfg))
	mac.Write(buf.Bytes())
	return hex.EncodeToString(mac.Sum(nil))
}

func uuid4() string {
	b := make([]byte, 16)
	rand.Read(b)
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b)
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32]
}

func maybeGunzip(data []byte) []byte {
	if len(data) >= 2 && data[0] == 0x1f && data[1] == 0x8b {
		zr, err := gzip.NewReader(bytes.NewReader(data))
		if err == nil {
			if out, err := io.ReadAll(io.LimitReader(zr, 8<<20)); err == nil {
				return out
			}
		}
	}
	return data
}

// rawCall performs one signed OEM gateway request and decodes the envelope.
func rawCall(cfg *Config, method, version string, payload any) (any, error) {
	return callGateway(cfg, method, version, payload, false)
}

func callGateway(cfg *Config, method, version string, payload any, auth bool) (any, error) {
	requestID := uuid4()
	var key []byte
	if auth {
		key = requestKeyAuth(cfg, requestID) // material alone: no ecode suffix
	} else {
		key = requestKey(cfg, requestID)
	}
	payloadJSON, _ := json.Marshal(payload)
	body := map[string]string{
		"clientId":   cfg.Static.ClientID,
		"appVersion": cfg.Static.AppVersion,
		"ttid":       cfg.Static.Ttid,
		"deviceId":   cfg.PhoneDeviceID,
		"os":         "Android",
		"lang":       "en",
		"et":         "3",
		"cp":         "gzip",
		"chKey":      cfg.Static.ChKey,
		"requestId":  requestID,
		"time":       strconv.FormatInt(time.Now().Unix(), 10),
		"a":          method,
		"v":          version,
		"postData":   et3Encrypt(key, payloadJSON),
	}
	if !auth {
		body["sid"] = cfg.Session.Sid // auth bodies carry no sid
	}
	body["sign"] = signBody(cfg, body)

	form := url.Values{}
	for k, v := range body {
		form.Set(k, v)
	}
	apiURL := normalizeEndpoint(cfg.Session.APIURL)
	if apiURL == "" {
		apiURL = "a1.tuyaeu.com"
	}
	req, err := http.NewRequest("POST", "https://"+apiURL+"/api.json", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept-Encoding", "gzip")
	resp, err := (&http.Client{Timeout: 25 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw := maybeGunzip(mustRead(resp.Body))
	var envelope map[string]any
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return nil, fmt.Errorf("non-JSON gateway response (http %d)", resp.StatusCode)
	}
	return decodeResult(cfg, envelope, key, 0)
}

func mustRead(r io.Reader) []byte {
	out, _ := io.ReadAll(io.LimitReader(r, 8<<20))
	return out
}

// decodeResult mirrors Business.decryptResponse: possibly-encrypted business
// envelope (verify MD5, ET3-decrypt, gunzip, recurse) then success/result.
func decodeResult(cfg *Config, envelope map[string]any, key []byte, depth int) (any, error) {
	if depth > 2 {
		return nil, fmt.Errorf("envelope recursion too deep")
	}
	if _, hasSuccess := envelope["success"]; !hasSuccess {
		ciphertext, _ := envelope["result"].(string)
		sign, _ := envelope["sign"].(string)
		t, _ := envelope["t"].(float64)
		if ciphertext == "" || sign == "" || envelope["t"] == nil {
			return nil, fmt.Errorf("unreadable gateway envelope")
		}
		canonical := fmt.Sprintf("result=%s||t=%d||", ciphertext, int64(t)) + string(key)
		d := md5.Sum([]byte(canonical))
		expected := hex.EncodeToString(d[:])
		if !strings.EqualFold(expected, sign) {
			return nil, fmt.Errorf("business response signature invalid")
		}
		clear, err := et3Decrypt(key, ciphertext)
		if err != nil {
			return nil, err
		}
		var inner map[string]any
		if err := json.Unmarshal(maybeGunzip(clear), &inner); err != nil {
			return nil, err
		}
		return decodeResult(cfg, inner, key, depth+1)
	}
	if envelope["success"] != true {
		return nil, fmt.Errorf("gateway error %v: %v", envelope["errorCode"], envelope["errorMsg"])
	}
	result := envelope["result"]
	switch v := result.(type) {
	case map[string]any, []any, nil, float64, bool:
		return v, nil
	case string:
		trimmed := strings.TrimSpace(v)
		if strings.HasPrefix(trimmed, "[") || strings.HasPrefix(trimmed, "{") {
			var parsed any
			if err := json.Unmarshal([]byte(trimmed), &parsed); err == nil {
				return parsed, nil
			}
		}
		clear, err := et3Decrypt(key, v)
		if err != nil {
			return nil, err
		}
		var parsed any
		if err := json.Unmarshal(maybeGunzip(clear), &parsed); err != nil {
			return nil, err
		}
		return parsed, nil
	}
	return nil, fmt.Errorf("unsupported result type")
}

var _ = os.Getenv
