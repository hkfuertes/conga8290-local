// S3 map storage: temporary creds from thing.m.dev.storage.config.get,
// file index from thing.m.dev.common.file.list, SigV4 presigned GETs.
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

type storageConfig struct {
	Provider string `json:"provider"`
	Endpoint string `json:"endpoint"`
	Region   string `json:"region"`
	Bucket   string `json:"bucket"`
	AK       string `json:"ak"`
	SK       string `json:"sk"`
	Token    string `json:"token"`
	Paths    map[string]string `json:"pathConfig"`
}

type fileEntry struct {
	Bucket  string `json:"bucket"`
	DevID   string `json:"devId"`
	File    string `json:"file"`
	FileType string `json:"fileType"`
	Extend  string `json:"extend"`
	ID      int64  `json:"id"`
	Time    int64  `json:"time"`
}

func getStorageConfig(cfg *Config) (*storageConfig, error) {
	res, err := rawCall(cfg, "thing.m.dev.storage.config.get", "1.0",
		map[string]any{"type": "Common", "devId": cfg.Session.DevID})
	if err != nil {
		return nil, err
	}
	b, _ := json.Marshal(res)
	var sc storageConfig
	if err := json.Unmarshal(b, &sc); err != nil || sc.AK == "" {
		return nil, fmt.Errorf("unexpected storage config: %.200s", string(b))
	}
	return &sc, nil
}

func listMapFiles(cfg *Config, limit int) ([]fileEntry, error) {
	res, err := rawCall(cfg, "thing.m.dev.common.file.list", "2.0", map[string]any{
		"devId": cfg.Session.DevID, "fileType": "pic",
		"limit": limit, "offset": 0, "gid": cfg.Session.Gid,
	})
	if err != nil {
		return nil, err
	}
	b, _ := json.Marshal(res)
	var wrapper struct {
		Datas      []fileEntry `json:"datas"`
		TotalCount int         `json:"totalCount"`
	}
	if err := json.Unmarshal(b, &wrapper); err != nil {
		return nil, fmt.Errorf("unexpected file list: %.200s", string(b))
	}
	return wrapper.Datas, nil
}

func hmacSHA256(key, msg []byte) []byte {
	mac := hmac.New(sha256.New, key)
	mac.Write(msg)
	return mac.Sum(nil)
}

// presignGet builds a query-style SigV4 presigned URL (recipe extracted from
// libThingCloudStorageSignatureTools.so; verified against ty-eu-storage-permanent).
func presignGet(sc *storageConfig, key string, expires int) string {
	key = strings.TrimPrefix(key, "/") // file.list keys arrive with a leading '/'
	host := sc.Bucket + "." + sc.Endpoint
	now := time.Now().UTC()
	amzDate := now.Format("20060102T150405Z")
	date := amzDate[:8]
	scope := date + "/" + sc.Region + "/s3/aws4_request"
	q := map[string]string{
		"X-Amz-Algorithm":     "AWS4-HMAC-SHA256",
		"X-Amz-Credential":    sc.AK + "/" + scope,
		"X-Amz-Date":          amzDate,
		"X-Amz-Expires":       fmt.Sprint(expires),
		"X-Amz-Security-Token": sc.Token,
		"X-Amz-SignedHeaders": "host",
	}
	keys := make([]string, 0, len(q))
	for k := range q {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(q[k]))
	}
	qs := strings.Join(parts, "&")
	canonical := "GET\n/" + key + "\n" + qs + "\nhost:" + host + "\n\nhost\nUNSIGNED-PAYLOAD"
	sts := "AWS4-HMAC-SHA256\n" + amzDate + "\n" + scope + "\n" + hex.EncodeToString(hash256([]byte(canonical)))
	kDate := hmacSHA256([]byte("AWS4"+sc.SK), []byte(date))
	kRegion := hmacSHA256(kDate, []byte(sc.Region))
	kService := hmacSHA256(kRegion, []byte("s3"))
	kSigning := hmacSHA256(kService, []byte("aws4_request"))
	sig := hex.EncodeToString(hmacSHA256(kSigning, []byte(sts)))
	return "https://" + host + "/" + key + "?" + qs + "&X-Amz-Signature=" + sig
}

func download(sc *storageConfig, key string) ([]byte, error) {
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Get(presignGet(sc, key, 3600))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 200))
		return nil, fmt.Errorf("S3 %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}
	return io.ReadAll(io.LimitReader(resp.Body, 32<<20))
}

func hash256(b []byte) []byte {
	h := sha256.Sum256(b)
	return h[:]
}
