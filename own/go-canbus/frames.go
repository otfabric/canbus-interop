// SPDX-License-Identifier: MIT

package main

import (
	"bufio"
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/otfabric/go-canbus"
)

const (
	sffMask    = 0x7FF
	effMask    = 0x1FFFFFFF
	xlMaxPrio  = 0x7FF
	xlMaxLen   = 2048
	fdMinMTU   = 72
	xlMinMTU   = 76 // CANXL_HDR_SIZE + 64
	slcanStart = "slcan:"
)

var fdLengths = map[int]bool{0: true, 1: true, 2: true, 3: true, 4: true, 5: true, 6: true, 7: true, 8: true,
	12: true, 16: true, 20: true, 24: true, 32: true, 48: true, 64: true}

// frameIn is a frame document as read: pointers tell absent from zero.
type frameIn struct {
	XL        *bool        `json:"xl"`
	ID        *json.Number `json:"id"`
	Extended  *bool        `json:"extended"`
	FD        *bool        `json:"fd"`
	BRS       *bool        `json:"brs"`
	ESI       *bool        `json:"esi"`
	Remote    *bool        `json:"remote"`
	Error     *bool        `json:"error"`
	Len       *json.Number `json:"len"`
	Data      *string      `json:"data"`
	Priority  *json.Number `json:"priority"`
	VCID      *json.Number `json:"vcid"`
	SEC       *bool        `json:"sec"`
	RRS       *bool        `json:"rrs"`
	SDT       *json.Number `json:"sdt"`
	AF        *json.Number `json:"af"`
	Timestamp any          `json:"timestamp"`
	Interface any          `json:"interface"`
}

// docFrame is one validated frame document: a CAN or CAN FD frame, or
// (contract 1.3) a CAN XL frame.
type docFrame struct {
	xl  bool
	can canbus.Frame
	x   canbus.XLFrame
}

func isSet(b *bool) bool { return b != nil && *b }

func intOf(n *json.Number, def int64) (int64, error) {
	if n == nil {
		return def, nil
	}
	return strconv.ParseInt(n.String(), 10, 64)
}

// parseFrame validates a frame document as the contract's Python adapters
// do (adapters/common/cbi.py): every violation is a usage error.
func parseFrame(line []byte) (docFrame, error) {
	var in frameIn
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.UseNumber()
	if err := dec.Decode(&in); err != nil {
		return docFrame{}, usageErr("frame document: %v", err)
	}
	var data []byte
	if in.Data != nil {
		var err error
		if data, err = hex.DecodeString(*in.Data); err != nil {
			return docFrame{}, usageErr("frame data is not hex: %q", *in.Data)
		}
	}
	if isSet(in.XL) {
		return parseXL(&in, data)
	}
	if in.ID == nil {
		return docFrame{}, usageErr("frame document without a valid id: %s", line)
	}
	id, err := intOf(in.ID, 0)
	if err != nil {
		return docFrame{}, usageErr("frame document without a valid id: %s", line)
	}
	n, err := intOf(in.Len, int64(len(data)))
	if err != nil {
		return docFrame{}, usageErr("bad len in %s", line)
	}
	ext, fd, brs, esi, rtr, errf := isSet(in.Extended), isSet(in.FD), isSet(in.BRS), isSet(in.ESI), isSet(in.Remote), isSet(in.Error)
	if errf && (ext || fd || rtr) {
		return docFrame{}, usageErr("an error frame is neither extended, FD nor remote")
	}
	limit := int64(sffMask)
	if ext || errf {
		limit = effMask
	}
	if id < 0 || id > limit {
		return docFrame{}, usageErr("identifier 0x%X out of range", id)
	}
	if fd {
		if rtr {
			return docFrame{}, usageErr("CAN FD frames have no remote form")
		}
		if !fdLengths[int(n)] {
			return docFrame{}, usageErr("CAN FD length %d is not a valid FD length", n)
		}
	} else {
		if brs || esi {
			return docFrame{}, usageErr("BRS/ESI only exist on CAN FD frames")
		}
		if n < 0 || n > 8 {
			return docFrame{}, usageErr("classical CAN length %d > 8", n)
		}
	}
	if rtr {
		if len(data) > 0 {
			return docFrame{}, usageErr("remote frame with data")
		}
	} else if int64(len(data)) != n {
		return docFrame{}, usageErr("len %d does not match %d data bytes", n, len(data))
	}
	var f canbus.Frame
	f.ID = canbus.ID(id)
	set := func(b bool, fl canbus.Flags) {
		if b {
			f.Flags |= fl
		}
	}
	set(ext, canbus.FlagExtended)
	set(fd, canbus.FlagFD)
	set(brs, canbus.FlagBRS)
	set(esi, canbus.FlagESI)
	set(rtr, canbus.FlagRemote)
	set(errf, canbus.FlagError)
	f.Len = uint8(n)
	copy(f.Data[:], data)
	return docFrame{can: f}, nil
}

func parseXL(in *frameIn, data []byte) (docFrame, error) {
	for name, present := range map[string]bool{"id": in.ID != nil, "extended": in.Extended != nil, "fd": in.FD != nil,
		"brs": in.BRS != nil, "esi": in.ESI != nil, "remote": in.Remote != nil, "error": in.Error != nil} {
		if present {
			return docFrame{}, usageErr("a CAN XL frame document has no %q", name)
		}
	}
	if in.Priority == nil {
		return docFrame{}, usageErr("CAN XL frame document without priority")
	}
	prio, e1 := intOf(in.Priority, 0)
	vcid, e2 := intOf(in.VCID, 0)
	sdt, e3 := intOf(in.SDT, 0)
	af, e4 := intOf(in.AF, 0)
	n, e5 := intOf(in.Len, int64(len(data)))
	for _, e := range []error{e1, e2, e3, e4, e5} {
		if e != nil {
			return docFrame{}, usageErr("bad CAN XL frame document: %v", e)
		}
	}
	if prio < 0 || prio > xlMaxPrio {
		return docFrame{}, usageErr("CAN XL priority 0x%X out of range", prio)
	}
	if vcid < 0 || vcid > 0xFF || sdt < 0 || sdt > 0xFF || af < 0 || af > 0xFFFFFFFF {
		return docFrame{}, usageErr("CAN XL vcid, sdt or af out of range")
	}
	if len(data) < 1 || len(data) > xlMaxLen || n != int64(len(data)) {
		return docFrame{}, usageErr("CAN XL len %d with %d data bytes (1..2048)", n, len(data))
	}
	x := canbus.XLFrame{Priority: uint16(prio), VCID: uint8(vcid), SDT: uint8(sdt), AF: uint32(af), Data: data}
	if isSet(in.SEC) {
		x.Flags |= canbus.XLSEC
	}
	if isSet(in.RRS) {
		x.Flags |= canbus.XLRRS
	}
	return docFrame{xl: true, x: x}, nil
}

// readLines reads the JSON Lines of a file ("-" = stdin), without blank
// lines and comments.
func readLines(name string) ([][]byte, error) {
	var r io.Reader = os.Stdin
	if name != "-" && name != "" {
		f, err := os.Open(name)
		if err != nil {
			return nil, usageErr("%v", err)
		}
		defer f.Close()
		r = f
	}
	var out [][]byte
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64<<10), 16<<20)
	for sc.Scan() {
		line := bytes.TrimSpace(sc.Bytes())
		if len(line) == 0 || line[0] == '#' {
			continue
		}
		out = append(out, append([]byte(nil), line...))
	}
	if err := sc.Err(); err != nil {
		return nil, ioErr("%s: %v", name, err)
	}
	return out, nil
}

func readFrames(name string) ([]docFrame, error) {
	lines, err := readLines(name)
	if err != nil {
		return nil, err
	}
	out := make([]docFrame, 0, len(lines))
	for i, l := range lines {
		f, err := parseFrame(l)
		if err != nil {
			var ae *adapterError
			if ok := asAdapterError(err, &ae); ok {
				ae.message = fmt.Sprintf("%s:%d: %s", name, i+1, ae.message)
			}
			return nil, err
		}
		out = append(out, f)
	}
	return out, nil
}

func asAdapterError(err error, ae **adapterError) bool {
	e, ok := err.(*adapterError)
	if ok {
		*ae = e
	}
	return ok
}

func timestamp(t time.Time) string {
	us := t.UnixMicro()
	return fmt.Sprintf("%d.%06d", us/1e6, us%1e6)
}

// frameDoc is the contract's frame document of a received frame.
func frameDoc(f *canbus.Frame, iface string) obj {
	d := obj{
		"id":       uint32(f.ID),
		"extended": f.IsExtended() && !f.IsError(),
		"fd":       f.IsFD(),
		"brs":      f.Flags&canbus.FlagBRS != 0,
		"esi":      f.Flags&canbus.FlagESI != 0,
		"remote":   f.IsRemote(),
		"error":    f.IsError(),
		"len":      int(f.Len),
		"data":     hex.EncodeToString(f.Payload()),
	}
	if !f.Timestamp.IsZero() {
		d["timestamp"] = timestamp(f.Timestamp)
	}
	if f.Interface != "" {
		d["interface"] = f.Interface
	} else if iface != "" {
		d["interface"] = iface
	}
	return d
}

func xlFrameDoc(x *canbus.XLFrame, iface string) obj {
	d := obj{
		"xl":       true,
		"priority": int(x.Priority),
		"vcid":     int(x.VCID),
		"sec":      x.Flags&canbus.XLSEC != 0,
		"rrs":      x.Flags&canbus.XLRRS != 0,
		"sdt":      int(x.SDT),
		"af":       x.AF,
		"len":      len(x.Data),
		"data":     hex.EncodeToString(x.Data),
	}
	if !x.Timestamp.IsZero() {
		d["timestamp"] = timestamp(x.Timestamp)
	}
	if x.Interface != "" {
		d["interface"] = x.Interface
	} else if iface != "" {
		d["interface"] = iface
	}
	return d
}

// parseFilter parses --filter <id>:<mask>[:e|:s][:inv] (hex) into the
// go-canbus filter with the same CAN_RAW_FILTER semantics.
func parseFilter(text string) (canbus.Filter, error) {
	parts := strings.Split(text, ":")
	if len(parts) < 2 {
		return canbus.Filter{}, usageErr("filter %q: want <id>:<mask>[:e|:s][:inv]", text)
	}
	id, err1 := strconv.ParseUint(parts[0], 16, 32)
	mask, err2 := strconv.ParseUint(parts[1], 16, 32)
	if err1 != nil || err2 != nil {
		return canbus.Filter{}, usageErr("filter %q: id and mask are hex", text)
	}
	f := canbus.Filter{ID: canbus.ID(id), Mask: canbus.ID(mask)}
	for _, p := range parts[2:] {
		switch p {
		case "e":
			f.Format = canbus.FormatExtended
		case "s":
			f.Format = canbus.FormatStandard
		case "inv":
			f.Invert = true
		default:
			return canbus.Filter{}, usageErr("filter %q: unknown modifier %q", text, p)
		}
	}
	return f, nil
}

// checkInterface fails with exit 4 when the interface is missing, down or
// has a smaller MTU than the operation needs.
func checkInterface(name string, fd, xl bool) error {
	if strings.HasPrefix(name, slcanStart) {
		return unsupportedErr("slcan interfaces")
	}
	if name == "" || strings.ContainsAny(name, "/\x00") || name == "." || name == ".." {
		return interfaceErr("interface %q does not exist", name)
	}
	base := "/sys/class/net/" + name
	if st, err := os.Stat(base); err != nil || !st.IsDir() {
		return interfaceErr("interface %s does not exist", name)
	}
	state, err1 := os.ReadFile(base + "/operstate")
	flags, err2 := os.ReadFile(base + "/flags")
	if err1 != nil || err2 != nil {
		return interfaceErr("interface %s: cannot read its state", name)
	}
	fl, err := strconv.ParseUint(strings.TrimPrefix(strings.TrimSpace(string(flags)), "0x"), 16, 32)
	if err != nil || fl&1 == 0 || strings.TrimSpace(string(state)) == "down" {
		return interfaceErr("interface %s is down", name)
	}
	mtu := 0
	if b, err := os.ReadFile(base + "/mtu"); err == nil {
		mtu, _ = strconv.Atoi(strings.TrimSpace(string(b)))
	}
	if fd && mtu < fdMinMTU {
		return interfaceErr("interface %s is not CAN FD capable (mtu %d < %d)", name, mtu, fdMinMTU)
	}
	if xl && mtu < xlMinMTU {
		return interfaceErr("interface %s is not CAN XL capable (mtu %d < %d)", name, mtu, xlMinMTU)
	}
	return nil
}
