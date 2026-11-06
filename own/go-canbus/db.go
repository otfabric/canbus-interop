// SPDX-License-Identifier: MIT

package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"math"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/otfabric/go-canbus/arxml"
	"github.com/otfabric/go-canbus/candb"
	"github.com/otfabric/go-canbus/dbc"
	"github.com/otfabric/go-canbus/kcd"
)

// loadDB parses a DBC, KCD or ARXML database, chosen by extension. A
// database go-canbus rejects is a usage error, as in the other adapters.
func loadDB(path string) (*candb.Database, error) {
	var (
		db    *candb.Database
		diags []candb.Diagnostic
		err   error
	)
	switch strings.ToLower(filepath.Ext(path)) {
	case ".dbc":
		db, diags, err = dbc.ParseFile(path)
	case ".kcd":
		db, diags, err = kcd.ParseFile(path)
	case ".arxml":
		db, diags, err = arxml.ParseFile(path)
	default:
		return nil, usageErr("%s: unsupported database format (.dbc, .kcd, .arxml)", path)
	}
	if err != nil {
		return nil, usageErr("%s: %v", path, err)
	}
	if candb.HasErrors(diags) {
		for _, d := range diags {
			if d.Severity == candb.Error {
				return nil, usageErr("%s: %v", path, d)
			}
		}
	}
	return db, nil
}

// physical is a physical value as the contract writes it: a number, or
// "nan", "inf", "-inf".
func physical(v float64) any {
	switch {
	case math.IsNaN(v):
		return "nan"
	case math.IsInf(v, 1):
		return "inf"
	case math.IsInf(v, -1):
		return "-inf"
	}
	return v
}

func opDecode(args []string) error {
	var dbPath, frames string
	fs := flagSet("decode")
	fs.StringVar(&dbPath, "db", "", "database")
	fs.StringVar(&frames, "frames", "-", "frame documents")
	if err := parse(fs, args); err != nil {
		return err
	}
	if dbPath == "" {
		return usageErr("decode: --db is required")
	}
	db, err := loadDB(dbPath)
	if err != nil {
		return err
	}
	docs, err := readFrames(frames)
	if err != nil {
		return err
	}
	for _, d := range docs {
		if d.xl {
			return unsupportedErr("decoding CAN XL frames")
		}
		f := &d.can
		id, ext := uint32(f.ID), f.IsExtended()
		if db.Message(f.ID, ext) == nil {
			emit(event("decode-error", obj{"id": id, "extended": ext, "error": "no message with this identifier"}))
			continue
		}
		m, sigs, err := db.DecodeFrame(f)
		if err != nil {
			emit(event("decode-error", obj{"id": id, "extended": ext, "error": err.Error()}))
			continue
		}
		signals := obj{}
		for _, s := range sigs {
			raw := s.Signal.RawString(s.Value)
			if s.Signal.ValueType != candb.Integer {
				raw = strconv.FormatUint(s.Raw, 10)
			}
			e := obj{"raw": raw, "physical": physical(s.Physical)}
			if s.Label != "" {
				e["label"] = s.Label
			}
			signals[s.Signal.Name] = e
		}
		emit(event("decoded", obj{"id": id, "extended": ext, "message": m.Name, "signals": signals}))
	}
	return nil
}

type encodeIn struct {
	Message string                     `json:"message"`
	Signals map[string]json.RawMessage `json:"signals"`
}

func opEncode(args []string) error {
	var dbPath, messages string
	var raw bool
	fs := flagSet("encode")
	fs.StringVar(&dbPath, "db", "", "database")
	fs.StringVar(&messages, "messages", "-", "message documents")
	fs.BoolVar(&raw, "raw", false, "raw values")
	if err := parse(fs, args); err != nil {
		return err
	}
	if dbPath == "" {
		return usageErr("encode: --db is required")
	}
	db, err := loadDB(dbPath)
	if err != nil {
		return err
	}
	lines, err := readLines(messages)
	if err != nil {
		return err
	}
	for i, line := range lines {
		var in encodeIn
		if err := json.Unmarshal(line, &in); err != nil {
			return usageErr("%s:%d: %v", messages, i+1, err)
		}
		m := db.MessageByName(in.Message)
		if m == nil {
			emit(event("encode-error", obj{"message": in.Message, "error": "no such message"}))
			continue
		}
		values := map[string]candb.Input{}
		var bad error
		for name, v := range in.Signals {
			in, err := input(v, raw)
			if err != nil {
				bad = err
				break
			}
			values[name] = in
		}
		if bad != nil {
			emit(event("encode-error", obj{"message": in.Message, "error": bad.Error()}))
			continue
		}
		data, err := m.EncodeWith(values, candb.EncodeOptions{})
		if err != nil {
			emit(event("encode-error", obj{"message": in.Message, "error": err.Error()}))
			continue
		}
		emit(event("encoded", obj{"message": m.Name, "id": uint32(m.ID), "extended": m.Extended, "data": hex.EncodeToString(data)}))
	}
	return nil
}

// input converts a signal value of an encode document: a number, a
// decimal string (raw values), or a value-table label.
func input(v json.RawMessage, raw bool) (candb.Input, error) {
	dec := json.NewDecoder(bytes.NewReader(v))
	dec.UseNumber()
	var x any
	if err := dec.Decode(&x); err != nil {
		return candb.Input{}, err
	}
	text := ""
	switch t := x.(type) {
	case json.Number:
		text = t.String()
	case string:
		text = t
	default:
		return candb.Input{}, usageErr("signal value %s is neither a number nor a string", v)
	}
	if !raw {
		if _, err := strconv.ParseFloat(text, 64); err != nil {
			return candb.Label(text), nil
		}
		return candb.PhysText(text), nil
	}
	if u, err := strconv.ParseUint(text, 10, 64); err == nil {
		return candb.Raw(u), nil
	}
	if s, err := strconv.ParseInt(text, 10, 64); err == nil {
		return candb.RawInt(s), nil
	}
	return candb.Input{}, usageErr("raw value %q is not an integer", text)
}
