// SPDX-License-Identifier: MIT

package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// capture runs the adapter with args and returns its stdout lines and exit code.
func runArgs(t *testing.T, args ...string) ([]map[string]any, int) {
	t.Helper()
	var buf bytes.Buffer
	stdout = &buf
	defer func() { stdout = os.Stdout }()
	code := run(args)
	var docs []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(buf.String()), "\n") {
		if line == "" {
			continue
		}
		var d map[string]any
		if err := json.Unmarshal([]byte(line), &d); err != nil {
			t.Fatalf("line %q: %v", line, err)
		}
		docs = append(docs, d)
	}
	return docs, code
}

func TestCapabilities(t *testing.T) {
	docs, code := runArgs(t)
	if code != 0 || len(docs) != 1 {
		t.Fatalf("exit %d, %v", code, docs)
	}
	ops := docs[0]["operations"].([]any)
	if len(ops) != len(handlers) {
		t.Fatalf("operations %v", ops)
	}
	docs, _ = runArgs(t, "print-version")
	if docs[0]["independentEngine"] != false || docs[0]["upstream"] != "go-canbus" {
		t.Fatalf("version %v", docs[0])
	}
}

func TestUnsupportedAndUsage(t *testing.T) {
	for _, c := range []struct {
		args []string
		code string
	}{
		{[]string{"log-convert", "--input", "x"}, "unsupported"},
		{[]string{"convert"}, "unsupported"},
		{[]string{"send", "--no-such-flag"}, "usage"},
		{[]string{"nonsense"}, "usage"},
		{[]string{"receive", "--interface", "slcan:socket://127.0.0.1:1"}, "unsupported"},
		{[]string{"receive", "--interface", "no-such-can9", "--timeout-ms", "10"}, "interface"},
		{[]string{"print-fixture", "../etc/passwd"}, "usage"},
	} {
		docs, code := runArgs(t, c.args...)
		want := 2
		if c.code == "interface" {
			want = 4
		}
		if code != want || len(docs) == 0 || docs[len(docs)-1]["code"] != c.code {
			t.Errorf("%v: exit %d, %v", c.args, code, docs)
		}
	}
}

func TestParseFrameRejectsMalformed(t *testing.T) {
	bad := []string{
		`{"id":291,"len":9,"data":"000102030405060708"}`,
		`{"id":291,"fd":true,"len":9,"data":"000102030405060708"}`,
		`{"id":2048,"len":0,"data":""}`,
		`{"id":536870912,"extended":true,"len":0,"data":""}`,
		`{"id":291,"len":4,"data":"0011"}`,
		`{"id":291,"brs":true,"len":0,"data":""}`,
		`{"id":291,"fd":true,"remote":true,"len":0,"data":""}`,
		`{"id":291,"len":1,"data":"zz"}`,
		`{"xl":true,"id":1,"priority":1,"len":1,"data":"00"}`,
		`{"xl":true,"priority":2048,"len":1,"data":"00"}`,
		`{"xl":true,"priority":1,"len":0,"data":""}`,
	}
	for _, b := range bad {
		if _, err := parseFrame([]byte(b)); err == nil {
			t.Errorf("%s accepted", b)
		} else if ae, ok := err.(*adapterError); !ok || ae.exit != exitUsage {
			t.Errorf("%s: %v", b, err)
		}
	}
	good := []string{
		`{"id":291,"extended":false,"fd":false,"brs":false,"esi":false,"remote":false,"error":false,"len":3,"data":"a1b2c3"}`,
		`{"id":291,"remote":true,"len":4,"data":""}`,
		`{"id":4,"error":true,"len":8,"data":"0004000000000000"}`,
		`{"xl":true,"priority":578,"vcid":66,"sec":true,"sdt":3,"af":3735928559,"len":3,"data":"a1b2c3"}`,
	}
	for _, g := range good {
		f, err := parseFrame([]byte(g))
		if err != nil {
			t.Errorf("%s: %v", g, err)
			continue
		}
		var round map[string]any
		var want map[string]any
		_ = json.Unmarshal([]byte(g), &want)
		var doc map[string]any
		if f.xl {
			doc = xlFrameDoc(&f.x, "")
		} else {
			doc = frameDoc(&f.can, "")
		}
		b, _ := json.Marshal(doc)
		_ = json.Unmarshal(b, &round)
		for k, v := range want {
			if round[k] != v {
				t.Errorf("%s: %s = %v, want %v", g, k, round[k], v)
			}
		}
	}
}

// TestFiltersAreKernelFilters checks the --filter notation against the
// struct can_filter values the Python adapters give the kernel
// (adapters/common/cbi.py).
func TestFiltersAreKernelFilters(t *testing.T) {
	const eff, inv = 0x80000000, 0x20000000
	for _, c := range []struct {
		text     string
		id, mask uint32
	}{
		{"123:7FF:s", 0x123, 0x7FF | eff},
		{"12345678:1FFFFFFF:e", 0x12345678 | eff, 0x1FFFFFFF | eff},
		{"123:7FF", 0x123, 0x7FF},
		{"100:700", 0x100, 0x700},
		{"123:7FF:s:inv", 0x123 | inv, 0x7FF | eff},
	} {
		f, err := parseFilter(c.text)
		if err != nil {
			t.Fatal(err)
		}
		id, mask := f.Kernel()
		if id != c.id || mask != c.mask {
			t.Errorf("%s: kernel %08x/%08x, want %08x/%08x", c.text, id, mask, c.id, c.mask)
		}
	}
	if _, err := parseFilter("1:2:x"); err == nil {
		t.Error("unknown modifier accepted")
	}
}

const testDBC = `VERSION ""

BU_: ECU

BO_ 291 Status: 4 ECU
 SG_ Speed : 0|16@1+ (0.1,0) [0|6553.5] "km/h" ECU
 SG_ Gear : 16|4@1+ (1,0) [0|15] "" ECU
 SG_ Temp : 24|8@1- (1,-40) [-168|87] "C" ECU

VAL_ 291 Gear 0 "Park" 1 "Drive" ;
`

func TestDecodeEncode(t *testing.T) {
	dir := t.TempDir()
	db := filepath.Join(dir, "t.dbc")
	frames := filepath.Join(dir, "f.jsonl")
	msgs := filepath.Join(dir, "m.jsonl")
	os.WriteFile(db, []byte(testDBC), 0o644)
	os.WriteFile(frames, []byte(`{"id":291,"len":4,"data":"e8030100"}`+"\n"+`{"id":292,"len":0,"data":""}`+"\n"), 0o644)
	os.WriteFile(msgs, []byte(`{"message":"Status","signals":{"Speed":100,"Gear":"Drive","Temp":-40}}`+"\n"+`{"message":"Nope","signals":{}}`+"\n"), 0o644)

	docs, code := runArgs(t, "decode", "--db", db, "--frames", frames)
	if code != 0 || len(docs) != 2 {
		t.Fatalf("decode exit %d: %v", code, docs)
	}
	sig := docs[0]["signals"].(map[string]any)
	if s := sig["Speed"].(map[string]any); s["raw"] != "1000" || s["physical"] != 100.0 {
		t.Errorf("Speed %v", s)
	}
	if g := sig["Gear"].(map[string]any); g["label"] != "Drive" {
		t.Errorf("Gear %v", g)
	}
	if docs[1]["type"] != "decode-error" {
		t.Errorf("unknown id: %v", docs[1])
	}

	docs, code = runArgs(t, "encode", "--db", db, "--messages", msgs)
	if code != 0 || len(docs) != 2 {
		t.Fatalf("encode exit %d: %v", code, docs)
	}
	if docs[0]["data"] != "e8030100" || docs[1]["type"] != "encode-error" {
		t.Errorf("encode %v", docs)
	}
}
