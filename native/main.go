// conga — single-binary client for the Conga 8290 (Tuya 3.3 LAN + Cecotec OEM cloud).
//
// Map-focused companion for tuya_local: reads tuya_local's config for LAN
// credentials, logs into the OEM cloud to recover the key and download maps.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type StaticCfg struct {
	MaterialHex string `json:"material_hex"`
	ChKey       string `json:"ch_key"`
	ClientID    string `json:"client_id"`
	AppVersion  string `json:"app_version"`
	Ttid        string `json:"ttid"`
}

type LanCfg struct {
	DeviceID string `json:"device_id"`
	IP       string `json:"ip"`
	LocalKey string `json:"local_key"`
	Port     int    `json:"port"`
}

type SessionCfg struct {
	Sid    string `json:"sid"`
	Ecode  string `json:"ecode"`
	APIURL string `json:"api_url"`
	Gid    int64  `json:"gid"`
	DevID  string `json:"dev_id"`
}

type Config struct {
	Static        StaticCfg  `json:"static"`
	PhoneDeviceID string     `json:"phone_device_id"`
	Lan           LanCfg     `json:"lan"`
	Session       SessionCfg `json:"session"`
}

const helpText = `conga 8290 — control LAN + mapas cloud en un solo binario

USO
  conga <comando> [argumentos]

COMANDOS
  status                         DPS completos del robot por LAN (solo lectura)
  roomclean <id...> [-passes n]  Limpiar habitaciones, p.ej. roomclean 3 5  [¡MUEVE el robot!]
  getmap [-wait 60] [-out maps]  get_both → espera subida → S3 → decode → .bin + .png
  decode <fich.bin>...           Decodifica mapas ya descargados → resumen + .png
  cloud <metodo> <ver> '<json>'  Llamada cruda al gateway OEM (debug/integración)

  extract <app.apk|app.xapk>     Rellena config.static desde el APK (material, ch_key, creds)
  login -email x@y -country 34   Login OEM: guarda sesión + recupera local_key
  initlan -from-tuyalocal <f>    Lee device_id/ip/local_key del YAML de tuya_local

CONFIG
  private/native.json (o $CONGA_CONFIG). extract/login/initlan lo rellenan solos.

NOTAS
  status/getmap/decode/cloud son de solo lectura.
  roomclean ordena MOVIMIENTO FÍSICO: el robot arranca a limpiar.
`

func configPath() string {
	if p := os.Getenv("CONGA_CONFIG"); p != "" {
		return p
	}
	return filepath.Join("private", "native.json")
}

func loadConfig() *Config {
	raw, err := os.ReadFile(configPath())
	if err != nil {
		fmt.Fprintf(os.Stderr, "config %s: %v\n(conga extract <app.xapk> para rellenarlo)\n", configPath(), err)
		os.Exit(1)
	}
	var c Config
	if err := json.Unmarshal(raw, &c); err != nil {
		fmt.Fprintf(os.Stderr, "config parse: %v\n", err)
		os.Exit(1)
	}
	if c.Lan.Port == 0 {
		c.Lan.Port = 6668
	}
	if c.Session.APIURL == "" {
		c.Session.APIURL = "a1.tuyaeu.com"
	}
	return &c
}

func saveConfig(c *Config) {
	if err := os.MkdirAll(filepath.Dir(configPath()), 0o700); err != nil {
		fatalIf(err, "mkdir config")
	}
	b, err := json.MarshalIndent(c, "", "  ")
	fatalIf(err, "config marshal")
	fatalIf(os.WriteFile(configPath(), append(b, '\n'), 0o600), "write config")
}

// loadOrCreate: extract/login/initlan want a config even if missing yet.
func loadOrCreate() *Config {
	if _, err := os.Stat(configPath()); err != nil {
		return &Config{Lan: LanCfg{Port: 6668}, Session: SessionCfg{APIURL: "a1.tuyaeu.com"}}
	}
	return loadConfig()
}

func fatalIf(err error, what string) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", what, err)
		os.Exit(1)
	}
}

func readLine(prompt string) string {
	fmt.Print(prompt)
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	return strings.TrimSpace(line)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Print(helpText)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "-h", "--help", "help":
		fmt.Print(helpText)

	case "status":
		cfg := loadConfig()
		dps, err := lanStatus(cfg)
		fatalIf(err, "status")
		type kv struct {
			K string
			V any
		}
		var out []kv
		for k, v := range dps {
			out = append(out, kv{k, v})
		}
		for i := 0; i < len(out); i++ {
			for j := i + 1; j < len(out); j++ {
				if numOrInf(out[j].K) < numOrInf(out[i].K) {
					out[i], out[j] = out[j], out[i]
				}
			}
		}
		for _, e := range out {
			s := fmt.Sprint(e.V)
			if len(s) > 80 {
				s = s[:77] + "..."
			}
			fmt.Printf("%4s = %s\n", e.K, s)
		}

	case "roomclean":
		fs := flag.NewFlagSet("roomclean", flag.ExitOnError)
		passes := fs.Int("passes", 1, "cleaning passes (1-3)")
		fs.Parse(args)
		rooms := fs.Args()
		if len(rooms) == 0 || *passes < 1 || *passes > 3 {
			fmt.Println("usage: conga roomclean <roomid...> [-passes n]   (room ids: 1..N, see conga decode)")
			os.Exit(2)
		}
		cfg := loadConfig()
		ids := make([]int, len(rooms))
		for i, r := range rooms {
			fmt.Sscanf(r, "%d", &ids[i])
		}
		frame := roomCleanFrame(*passes, ids)
		fmt.Printf("sending room-clean frame: %x (rooms %v, %d passes)\n", frame, ids, *passes)
		got, err := lanControl(cfg, map[string]any{"15": b64(frame)}, 6)
		fatalIf(err, "roomclean")
		fmt.Println("device replied:", dpsString(got))

	case "getmap":
		fs := flag.NewFlagSet("getmap", flag.ExitOnError)
		wait := fs.Int("wait", 60, "seconds to wait for the robot to upload")
		outdir := fs.String("out", "maps", "output directory")
		asJSON := fs.Bool("json", false, "machine-readable output (rooms + calibration)")
		fs.Parse(args)
		cfg := loadConfig()
		path, sum, err := getMapMode(cfg, *wait, *outdir, *asJSON)
		fatalIf(err, "getmap")
		fmt.Printf("map saved: %s\n%s\n", path, sum)

	case "decode":
		asJSON := false
		var files []string
		for _, a := range args {
			if a == "--json" || a == "-json" {
				asJSON = true
				continue
			}
			files = append(files, a)
		}
		if len(files) == 0 {
			fmt.Println("usage: conga decode [--json] maps/foo.bin")
			os.Exit(2)
		}
		for _, f := range files {
			sum, err := decodeFileMode(f, asJSON)
			fatalIf(err, f)
			fmt.Printf("%s\n%s\n", f, sum)
		}

	case "cloud":
		if len(args) < 3 {
			fmt.Println(`usage: conga cloud thing.m.dev.common.file.list 2.0 '{"devId":"...","fileType":"pic"}'`)
			os.Exit(2)
		}
		cfg := loadConfig()
		var payload any
		fatalIf(json.Unmarshal([]byte(args[2]), &payload), "payload json")
		res, err := rawCall(cfg, args[0], args[1], payload)
		fatalIf(err, args[0])
		b, _ := json.MarshalIndent(res, "", "  ")
		fmt.Println(string(b))

	case "extract":
		if len(args) < 1 {
			fmt.Println("usage: conga extract <cecotec.apk|cecotec.xapk>   (fills config static section)")
			os.Exit(2)
		}
		st, err := extractStatic(args[0])
		fatalIf(err, "extract")
		cfg := loadOrCreate()
		cfg.Static = StaticCfg{
			MaterialHex: st.Material, ChKey: st.ChKey, ClientID: st.AppKey,
			AppVersion: st.AppVersion, Ttid: st.Ttid,
		}
		saveConfig(cfg)
		fmt.Printf("config %s actualizado (static):\n  package     %s\n  client_id   %s\n  app_version %s\n  ttid        %s\n  ch_key      %s\n  material    %d bytes\n",
			configPath(), st.Package, st.AppKey, st.AppVersion, st.Ttid, st.ChKey, len(st.Material)/2)

	case "login":
		fs := flag.NewFlagSet("login", flag.ExitOnError)
		email := fs.String("email", "", "Cecotec account email")
		country := fs.String("country", "34", "country code")
		pwFile := fs.String("password-file", "", "read password from file")
		pwArg := fs.String("password", "", "password (exposed on cmdline; prefer the prompt)")
		fs.Parse(args)
		if *email == "" {
			fmt.Println("usage: conga login -email you@example.com [-country 34]")
			os.Exit(2)
		}
		password := *pwArg
		if password == "" && *pwFile != "" {
			b, err := os.ReadFile(*pwFile)
			fatalIf(err, "password-file")
			password = strings.TrimSpace(string(b))
		}
		if password == "" {
			password = readLine("password: ")
		}
		loginCommand(*email, *country, password)

	case "initlan":
		fs := flag.NewFlagSet("initlan", flag.ExitOnError)
		from := fs.String("from-tuyalocal", "", "path to tuya_local YAML")
		ip := fs.String("ip", "", "override/robot IP")
		fs.Parse(args)
		if *from == "" {
			fmt.Println("usage: conga initlan -from-tuyalocal /config/tuya_local.yaml [-ip 192.168.x.x]")
			os.Exit(2)
		}
		initLanCommand(*from, *ip)

	default:
		fmt.Printf("unknown command %q\n", cmd)
		os.Exit(2)
	}
}

func numOrInf(s string) int {
	n := 0
	for _, c := range strings.TrimSpace(s) {
		if c < '0' || c > '9' {
			return 1 << 30
		}
		n = n*10 + int(c-'0')
	}
	return n
}

func dpsString(dps map[string]any) string {
	if len(dps) == 0 {
		return "(no dps in reply)"
	}
	b, _ := json.Marshal(dps)
	return string(b)
}
