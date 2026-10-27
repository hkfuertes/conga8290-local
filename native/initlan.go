package main

// initlan — fill the lan config section from a tuya_local YAML.
// Minimal targeted scan: tuya_local device blocks carry device_id/local_key/host
// at fixed keys; entities never use those key names, so first-occurrence works.

import (
	"fmt"
	"os"
	"strings"
)

func initLanCommand(yamlPath, ipOverride string) {
	raw, err := os.ReadFile(yamlPath)
	fatalIf(err, "read yaml")
	var deviceID, localKey, host, proto string
	for _, line := range strings.Split(string(raw), "\n") {
		l := strings.TrimSpace(line)
		get := func(key string) (string, bool) {
			if v, ok := strings.CutPrefix(l, key+":"); ok {
				v = strings.TrimSpace(v)
				v = strings.Trim(v, `"'`)
				return v, v != ""
			}
			return "", false
		}
		if deviceID == "" {
			deviceID, _ = get("device_id")
		}
		if localKey == "" {
			localKey, _ = get("local_key")
		}
		if host == "" {
			host, _ = get("host")
		}
		if proto == "" {
			proto, _ = get("protocol_version")
		}
	}
	if deviceID == "" || localKey == "" {
		fatalIf(fmt.Errorf("device_id/local_key no encontrados en %s (¿formato tuya_local?)", yamlPath), "initlan")
	}
	cfg := loadOrCreate()
	cfg.Lan.DeviceID, cfg.Lan.LocalKey = deviceID, localKey
	if ipOverride != "" {
		cfg.Lan.IP = ipOverride
	} else if host != "" {
		cfg.Lan.IP = host
	}
	if proto != "" && proto != "3.3" {
		fmt.Printf("aviso: protocol_version=%s (este binario habla 3.3)\n", proto)
	}
	if cfg.Session.DevID == "" {
		cfg.Session.DevID = deviceID
	}
	saveConfig(cfg)
	fmt.Printf("config %s actualizado (lan):\n  device_id %s\n  ip        %s\n  local_key %s…\n",
		configPath(), deviceID, cfg.Lan.IP, trim(cfg.Lan.LocalKey, 6))
	if cfg.Static.MaterialHex == "" {
		fmt.Println("siguiente paso: conga extract <app.xapk>  y  conga login -email …")
	}
}
