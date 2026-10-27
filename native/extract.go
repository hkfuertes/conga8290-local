package main

// conga extract <apk|xapk> — derives the static cloud constants (material,
// ch_key, app credentials) from the shipped app package, fully offline.
//
// Reverse-engineered from the app's native libs (see MAPS.md / commit history):
//   - app credentials: BuildConfig static fields in classes*.dex
//   - decoded key: assets/t_s.bmp carrier (v1) — strings scattered in pixel
//     data, located via a Java-string hash walk, reassembled by solving an
//     exact-rational Vandermonde system (imath mp_rat in the original .so;
//     math/big.Rat here). Verified against the shipped 1.2.9 artifact.
//   - fingerprint: SHA-256 of the APK v2/v3 signing certificate (DER)
//   - material = package + '_' + fingerprint + '_' + decodedKey + '_' + secret
//   - ch_key = HMAC-SHA256(appkey, package+'_'+fingerprint)[8:16]

import (
	"archive/zip"
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"strings"
)

const buildConfigClass = "Lcom/thingclips/sample/BuildConfig;"

type appStatic struct {
	Package, AppKey, Secret, Ttid, AppVersion string
	Material, ChKey                          string
}

// ---------- dex BuildConfig statics ----------

func dexBuildConfig(dex []byte) map[string]interface{} {
	if len(dex) < 112 || !bytes.HasPrefix(dex, []byte("dex\n")) {
		return nil
	}
	u32 := func(o int) uint32 { return binary.LittleEndian.Uint32(dex[o:]) }
	uleb := func(o int) (uint64, int) {
		var r uint64
		for s := uint(0); s < 35; s += 7 {
			b := dex[o]
			o++
			r |= uint64(b&127) << s
			if b < 128 {
				return r, o
			}
		}
		return 0, 0 // invalid
	}
	cnt, off := int(u32(56)), int(u32(60))
	strs := make([]string, 0, cnt)
	for i := 0; i < cnt; i++ {
		p := int(u32(off + 4*i))
		_, p = uleb(p)
		end := bytes.IndexByte(dex[p:], 0)
		if end < 0 {
			return nil
		}
		strs = append(strs, string(dex[p:p+end]))
	}
	cnt, off = int(u32(64)), int(u32(68))
	types := make([]string, cnt)
	for i := range types {
		types[i] = strs[u32(off+4*i)]
	}
	found := false
	for _, t := range types {
		if t == buildConfigClass {
			found = true
			break
		}
	}
	if !found {
		return nil
	}
	cnt, off = int(u32(80)), int(u32(84))
	fields := make([]string, cnt)
	for i := range fields {
		fields[i] = strs[u32(off+8*i+4)]
	}
	cnt, off = int(u32(96)), int(u32(100))
	for i := 0; i < cnt; i++ {
		d := off + 32*i
		if types[u32(d)] != buildConfigClass {
			continue
		}
		p := int(u32(d + 24))
		var counts [4]uint64
		for j := range counts {
			counts[j], p = uleb(p)
		}
		fi, names := 0, []string{}
		for j := uint64(0); j < counts[0]; j++ {
			delta, np := uleb(p)
			p = np
			fi += int(delta)
			_, p = uleb(p)
			names = append(names, fields[fi])
		}
		p = int(u32(d + 28))
		vc, np := uleb(p)
		p = np
		out := map[string]interface{}{}
		for _, name := range names[:vc] {
			if p >= len(dex) {
				break
			}
			tag := dex[p]
			p++
			kind, arg := tag&31, int(tag>>5)
			switch kind {
			case 0x1e, 0x1f: // null / boolean: no payload
				continue
			case 0x00, 0x02, 0x03, 0x04, 0x06, 0x10, 0x11:
				size := arg + 1
				v := uint64(0)
				for j := 0; j < size; j++ {
					v |= uint64(dex[p+j]) << (8 * uint(j))
				}
				p += size
				out[name] = v
			case 0x17: // string
				v := uint64(0)
				for j := 0; j < arg+1; j++ {
					v |= uint64(dex[p+j]) << (8 * uint(j))
				}
				p += arg + 1
				if int(v) < len(strs) {
					out[name] = strs[v]
				}
			default:
				return out // unsupported value type after the ones we need
			}
		}
		return out
	}
	return nil
}

// ---------- APK v2/v3 signing certificate ----------

func lp32(b []byte, off int) ([]byte, int, error) {
	if off+4 > len(b) {
		return nil, 0, errors.New("truncated lp32")
	}
	n := int(binary.LittleEndian.Uint32(b[off:]))
	s, e := off+4, off+4+n
	if e > len(b) {
		return nil, 0, errors.New("truncated lp32 body")
	}
	return b[s:e], e, nil
}

func signingCert(apk []byte) ([]byte, error) {
	window := 65557
	if len(apk) < window {
		window = len(apk)
	}
	eocd := bytes.LastIndex(apk[len(apk)-window:], []byte("PK\x05\x06"))
	if eocd < 0 {
		return nil, errors.New("eocd missing")
	}
	eocd += len(apk) - window
	if binary.LittleEndian.Uint16(apk[eocd+20:]) != 0 || eocd+22 != len(apk) {
		return nil, errors.New("eocd not at end")
	}
	dir := int(binary.LittleEndian.Uint32(apk[eocd+16:]))
	if dir < 24 || dir > eocd || string(apk[dir-16:dir]) != "APK Sig Block 42" {
		return nil, errors.New("signing block missing")
	}
	size := int(binary.LittleEndian.Uint64(apk[dir-24:]))
	start := dir - size - 8
	if start < 0 || binary.LittleEndian.Uint64(apk[start:]) != uint64(size) {
		return nil, errors.New("signing block size invalid")
	}
	pos, end := start+8, dir-24
	schemes := map[uint32][]byte{}
	for pos < end {
		if pos+12 > end {
			return nil, errors.New("truncated pair")
		}
		ps := int(binary.LittleEndian.Uint64(apk[pos:]))
		pe := pos + 8 + ps
		if ps < 4 || pe > end {
			return nil, errors.New("truncated pair")
		}
		schemes[binary.LittleEndian.Uint32(apk[pos+8:])] = apk[pos+12 : pe]
		pos = pe
	}
	scheme := uint32(0x7109871a)
	if _, ok := schemes[scheme]; !ok {
		scheme = 0xf05368c0
	}
	if _, ok := schemes[scheme]; !ok {
		return nil, errors.New("no v2/v3 signing scheme")
	}
	signers, _, err := lp32(schemes[scheme], 0)
	if err != nil {
		return nil, err
	}
	signer, remaining, err := lp32(signers, 0)
	if err != nil {
		return nil, err
	}
	if remaining != len(signers) {
		return nil, errors.New("multiple signers")
	}
	signedData, _, err := lp32(signer, 0)
	if err != nil {
		return nil, err
	}
	_, p, err := lp32(signedData, 0) // digest records
	if err != nil {
		return nil, err
	}
	certificates, _, err := lp32(signedData, p)
	if err != nil {
		return nil, err
	}
	cert, _, err := lp32(certificates, 0)
	if err != nil {
		return nil, err
	}
	if len(cert) < 32 || len(cert) > 16384 {
		return nil, errors.New("bad certificate size")
	}
	return cert, nil
}

func fingerprint(cert []byte) string {
	d := sha256.Sum256(cert)
	return strings.ToUpper(hex.EncodeToString(d[:]))
}

func colonHex(h string) string {
	var b strings.Builder
	for i := 0; i < len(h); i += 2 {
		if i > 0 {
			b.WriteByte(':')
		}
		b.WriteString(h[i : i+2])
	}
	return b.String()
}

// ---------- t_s.bmp carrier (v1), verified against shipped 1.2.9 ----------

func javaHash(s string) uint32 {
	var h uint32
	for i := 0; i < len(s); i++ {
		h = h*31 + uint32(s[i])
	}
	if h >= 0x80000000 {
		h = 0 - h // abs() over int32 range, wraps in uint32
	}
	return h
}

type pair struct{ a, b *big.Int }

func carrierKeys(appID string, bmp []byte) ([]string, error) {
	if len(bmp) < 54 || bmp[0] != 'B' || bmp[1] != 'M' {
		return nil, errors.New("not a BMP carrier")
	}
	declared := binary.LittleEndian.Uint32(bmp[2:])
	off := binary.LittleEndian.Uint32(bmp[10:])
	bpp := binary.LittleEndian.Uint16(bmp[28:])
	if declared < 0x2800 || declared > 0x200000 || int(declared) > len(bmp) || off != 54 ||
		(bpp != 24 && bpp != 32) || binary.LittleEndian.Uint32(bmp[30:]) != 0 {
		return nil, errors.New("unsupported carrier layout")
	}
	data := bmp[54:]
	ln := uint32(len(data))
	at := func(i uint32) byte { return data[i%ln] }
	u32 := func(i uint32) uint32 {
		return uint32(at(i))<<24 | uint32(at(i+1))<<16 | uint32(at(i+2))<<8 | uint32(at(i+3))
	}
	base := (javaHash(appID) % ln) >> 1
	if at(base) != 1 {
		return nil, fmt.Errorf("carrier version %d unsupported (only v1 known)", at(base))
	}
	count := int(at(base + 1))
	segs := int(at(base + 2))
	if count < 1 || count > 5 || segs < 1 {
		return nil, errors.New("bad carrier header")
	}
	o := (u32(base+3) ^ base) % ln
	pairs := make([]pair, segs)
	for i := range pairs {
		lenA := int(at(o))
		posA := (o + 1) % ln
		a, ok := new(big.Int).SetString(hexAt(data, ln, posA, lenA), 16)
		if !ok {
			return nil, errors.New("carrier segment A not hex")
		}
		pos2 := (posA + uint32(lenA)) % ln
		lenB := int(at(pos2))
		posB := (pos2 + 1) % ln
		b, ok := new(big.Int).SetString(hexAt(data, ln, posB, lenB), 16)
		if !ok {
			return nil, errors.New("carrier segment B not hex")
		}
		pairs[i] = pair{a, b}
		o = (u32((posB+uint32(lenB))%ln) ^ o) % ln
	}
	out := make([]string, 0, count)
	stride := segs / count
	for j := 0; j < count; j++ {
		chunk := pairs[j*stride : (j+1)*stride]
		s, err := solveCarrier(chunk)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, nil
}

func hexAt(data []byte, ln, start uint32, n int) string {
	var b strings.Builder
	for i := uint32(0); i < uint32(n); i++ {
		fmt.Fprintf(&b, "%02x", data[(start+i)%ln])
	}
	return b.String()
}

// solveCarrier: exact Gauss-Jordan on the Vandermonde system
// [A^n..A^0 | B] rows; the solution's last variable must be an integer whose
// big-endian bytes are the hidden string.
func solveCarrier(pairs []pair) (string, error) {
	n := len(pairs)
	rows := make([][]*big.Rat, n)
	for i, p := range pairs {
		row := make([]*big.Rat, n+1)
		for k := 0; k < n; k++ {
			e := new(big.Int).Exp(p.a, big.NewInt(int64(n-1-k)), nil)
			row[k] = new(big.Rat).SetInt(e)
		}
		row[n] = new(big.Rat).SetInt(p.b)
		rows[i] = row
	}
	for i := 0; i < n; i++ {
		piv := -1
		for r := i; r < n; r++ {
			if rows[r][i].Sign() != 0 {
				piv = r
				break
			}
		}
		if piv < 0 {
			return "", errors.New("singular carrier matrix")
		}
		rows[i], rows[piv] = rows[piv], rows[i]
		for r := 0; r < n; r++ {
			if r != i && rows[r][i].Sign() != 0 {
				f := new(big.Rat).Quo(rows[r][i], rows[i][i])
				for c := i; c <= n; c++ {
					t := new(big.Rat).Mul(f, rows[i][c])
					rows[r][c].Sub(rows[r][c], t)
				}
			}
		}
	}
	x := new(big.Rat).Quo(rows[n-1][n], rows[n-1][n-1])
	if x.Denom().Cmp(big.NewInt(1)) != 0 {
		return "", errors.New("carrier solution not integral")
	}
	num := x.Num()
	if num.Sign() < 0 {
		return "", errors.New("negative carrier solution")
	}
	raw := num.Bytes() // big-endian magnitude
	z := 0
	for z < len(raw) && raw[z] == 0 {
		z++
	}
	return hex.EncodeToString(raw[z:]), nil
}

// ---------- package entry ----------

func extractStatic(path string) (*appStatic, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	fi, _ := f.Stat()
	if filepath.Ext(path) == ".xapk" || filepath.Ext(path) == ".apk" {
		// both are zips; for XAPK find the base (non-config) APK entry
		zr, err := zip.NewReader(f, fi.Size())
		if err != nil {
			return nil, err
		}
		for _, z := range zr.File {
			name := filepath.Base(z.Name)
			if strings.HasSuffix(name, ".apk") && !strings.HasPrefix(name, "config.") {
				rc, err := z.Open()
				if err != nil {
					return nil, err
				}
				apk, err := io.ReadAll(rc)
				rc.Close()
				if err != nil {
					return nil, err
				}
				return extractFromAPK(apk)
			}
		}
		// maybe a plain APK passed with odd extension, or an .apk direct zip
		if apk, err := io.ReadAll(f); err == nil && len(apk) > 4 && apk[0] == 'P' && apk[1] == 'K' {
			return extractFromAPK(apk)
		}
		return nil, errors.New("no base APK inside package")
	}
	return nil, errors.New("expected .apk or .xapk")
}

func extractFromAPK(apk []byte) (*appStatic, error) {
	zr, err := zip.NewReader(bytes.NewReader(apk), int64(len(apk)))
	if err != nil {
		return nil, err
	}
	// BuildConfig statics
	var bc map[string]interface{}
	for _, z := range zr.File {
		if strings.HasPrefix(z.Name, "classes") && strings.HasSuffix(z.Name, ".dex") && bc == nil {
			rc, err := z.Open()
			if err != nil {
				continue
			}
			dex, _ := io.ReadAll(rc)
			rc.Close()
			if m := dexBuildConfig(dex); m != nil {
				bc = m
			}
		}
	}
	if bc == nil {
		return nil, errors.New("BuildConfig not found in any dex")
	}
	getStr := func(k string) string { v, _ := bc[k].(string); return v }
	pkg, appKey, secret := getStr("APPLICATION_ID"), getStr("THING_SMART_APPKEY"), getStr("THING_SMART_SECRET")
	flavor, version := getStr("FLAVOR"), getStr("VERSION_NAME")
	if pkg == "" || appKey == "" || secret == "" {
		return nil, errors.New("app credentials missing from BuildConfig")
	}
	// carrier key
	var bmp []byte
	for _, z := range zr.File {
		if z.Name == "assets/t_s.bmp" {
			rc, _ := z.Open()
			bmp, _ = io.ReadAll(rc)
			rc.Close()
		}
	}
	if bmp == nil {
		return nil, errors.New("assets/t_s.bmp missing")
	}
	keys, err := carrierKeys(appKey, bmp)
	if err != nil {
		return nil, err
	}
	if len(keys) != 1 {
		return nil, fmt.Errorf("expected 1 carrier key, got %d", len(keys))
	}
	decoded, err := hex.DecodeString(keys[0])
	if err != nil {
		return nil, err
	}
	// fingerprint
	cert, err := signingCert(apk)
	if err != nil {
		return nil, err
	}
	fp := colonHex(fingerprint(cert))
	material := strings.Join([]string{pkg, fp, string(decoded), secret}, "_")
	// ch_key
	mac := hmac.New(sha256.New, []byte(appKey))
	mac.Write([]byte(pkg + "_" + fp))
	chKey := hex.EncodeToString(mac.Sum(nil))[8:16]
	ttid := "sdk_" + flavor + "@" + appKey
	return &appStatic{
		Package: pkg, AppKey: appKey, Secret: secret, Ttid: ttid, AppVersion: version,
		Material: hex.EncodeToString([]byte(material)), ChKey: chKey,
	}, nil
}
