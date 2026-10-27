package main

// conga login — OEM cloud login (oem-ui flow), fully static-crypto:
//   1. smartlife.m.user.username.token.get 2.0 {countryCode,username,isUid:false}
//      -> {token, publicKey(decimal), exponent(decimal)}
//   2. passwd = RSA-PKCS1v15(MD5(password).hex, n/e) hex
//   3. smartlife.m.user.email.password.login 3.0 -> {sid, ecode, domain.mobileApiUrl}
//   4. m.life.home.space.list 1.0 -> gid
//   5. m.life.my.group.device.list 2.2 {gid} -> devId + local_key (fills lan)

import (
	"crypto/md5"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"
)

const congaProduct = "kofl9ubyyyfznpxw"

func normalizeEndpoint(u string) string {
	u = strings.TrimPrefix(strings.TrimPrefix(u, "https://"), "http://")
	if i := strings.IndexByte(u, '/'); i >= 0 {
		u = u[:i]
	}
	if !strings.Contains(u, "a1.tuyaeu.com") {
		return ""
	}
	return u
}

func loginCommand(email, country, password string) {
	cfg := loadOrCreate()
	if cfg.Static.MaterialHex == "" {
		fmt.Println("config.static vacío: ejecuta antes 'conga extract <app.xapk>'")
		os.Exit(1)
	}
	if cfg.PhoneDeviceID == "" {
		b := make([]byte, 11)
		if _, err := rand.Read(b); err != nil {
			fatalIf(err, "rand")
		}
		cfg.PhoneDeviceID = hex.EncodeToString(b)
	}

	// 1. username token
	res, err := callGateway(cfg, "smartlife.m.user.username.token.get", "2.0",
		map[string]any{"countryCode": country, "username": email, "isUid": false}, true)
	fatalIf(err, "username.token.get")
	token, _ := res.(map[string]any)
	pubStr, _ := token["publicKey"].(string)
	expStr, _ := token["exponent"].(string)
	tokenStr, _ := token["token"].(string)
	if pubStr == "" || expStr == "" || tokenStr == "" {
		b, _ := json.MarshalIndent(res, "", " ")
		fmt.Printf("login response sin token/RSA:\n%s\n", b)
		os.Exit(1)
	}
	n, ok1 := new(big.Int).SetString(pubStr, 10)
	e, ok2 := new(big.Int).SetString(expStr, 10)
	if !ok1 || !ok2 || !e.IsInt64() {
		fatalIf(fmt.Errorf("RSA decimal keys no válidos"), "rsa")
	}
	pub := &rsa.PublicKey{N: n, E: int(e.Int64())}
	if _, err := x509.MarshalPKIXPublicKey(pub); err != nil {
		fatalIf(err, "rsa key") // sanity
	}

	// 2. RSA-encrypt the lowercase MD5 hex of the password
	digest := fmt.Sprintf("%x", md5.Sum([]byte(password)))
	enc, err := rsa.EncryptPKCS1v15(rand.Reader, pub, []byte(digest))
	fatalIf(err, "rsa encrypt")

	// 3. password login
	res, err = callGateway(cfg, "smartlife.m.user.email.password.login", "3.0",
		map[string]any{
			"countryCode": country,
			"email":       email,
			"passwd":      hex.EncodeToString(enc),
			"token":       tokenStr,
			"ifencrypt":   1,
			"options":     `{"group":1,"mfaCode": ""}`,
		}, true)
	fatalIf(err, "email.password.login")
	login, _ := res.(map[string]any)
	sid, _ := login["sid"].(string)
	ecode, _ := login["ecode"].(string)
	if sid == "" || ecode == "" {
		b, _ := json.MarshalIndent(res, "", " ")
		fmt.Printf("login falló:\n%s\n", b)
		os.Exit(1)
	}
	cfg.Session.Sid, cfg.Session.Ecode = sid, ecode
	if domain, ok := login["domain"].(map[string]any); ok {
		if u, ok := domain["mobileApiUrl"].(string); ok {
			if host := normalizeEndpoint(u); host != "" {
				cfg.Session.APIURL = host
			}
		}
	}
	fmt.Println("· sesión creada")

	// 4. homes -> gid
	res, err = rawCall(cfg, "m.life.home.space.list", "1.0", map[string]any{})
	fatalIf(err, "home.space.list")
	homes, _ := res.([]any)
	if len(homes) == 0 {
		fatalIf(fmt.Errorf("sin hogares en la cuenta"), "home.space.list")
	}
	home, _ := homes[0].(map[string]any)
	gid := jsonInt(home["gid"])
	if gid == 0 {
		gid = jsonInt(home["id"])
	}
	cfg.Session.Gid = gid
	fmt.Printf("· hogar gid=%d\n", gid)

	// 5. devices -> robot devId + local_key
	res, err = rawCall(cfg, "m.life.my.group.device.list", "2.2", map[string]any{"gid": fmt.Sprint(gid)})
	fatalIf(err, "device.list")
	devs := devicesOf(res)
	for _, d := range devs {
		if fmt.Sprint(d["productId"]) != congaProduct {
			continue
		}
		devID, _ := d["devId"].(string)
		localKey, _ := d["localKey"].(string)
		if devID == "" || localKey == "" {
			continue
		}
		cfg.Session.DevID = devID
		cfg.Lan.DeviceID = devID
		cfg.Lan.LocalKey = localKey
		break
	}
	if cfg.Session.DevID == "" {
		fmt.Println("· aviso: robot no encontrado en la lista de dispositivos (¿otra app/region?)")
	}

	saveConfig(cfg)
	fmt.Printf("config %s guardado:\n", configPath())
	fmt.Printf("  session: sid=%s… ecode=%s api=%s\n", trim(cfg.Session.Sid, 8), cfg.Session.Ecode, cfg.Session.APIURL)
	if cfg.Session.DevID != "" {
		fmt.Printf("  robot:   devId=%s\n           local_key recuperada=%s\n", cfg.Session.DevID, trim(cfg.Lan.LocalKey, 6))
	}
	if cfg.Lan.IP == "" {
		fmt.Println("  falta lan.ip → conga initlan -from-tuyalocal <yaml>  (o -ip manual)")
	}
}

func devicesOf(res any) []map[string]any {
	var out []map[string]any
	if l, ok := res.([]any); ok {
		for _, it := range l {
			if m, ok := it.(map[string]any); ok {
				out = append(out, m)
			}
		}
	} else if m, ok := res.(map[string]any); ok {
		if l, ok := m["devices"].([]any); ok {
			return devicesOf(l)
		}
		if l, ok := m["list"].([]any); ok {
			return devicesOf(l)
		}
	}
	return out
}

func jsonInt(v any) int64 {
	switch x := v.(type) {
	case float64:
		return int64(x)
	case string:
		var n int64
		fmt.Sscanf(x, "%d", &n)
		return n
	}
	return 0
}

func trim(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
